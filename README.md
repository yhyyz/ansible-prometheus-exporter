# ansible-prometheus-exporter

[toc]

### EMR Monitor

#### 更新

##### 2021-07-11

```markdown
# 修复由于自动metadata生产造成的resize不触发，同时设定从sqs数据的可见性超时为600s
1. 需要重新生成meta信息，即执行 ansible-playbook --connection=local  -i  localhost, -u ec2-user  atuometa_playbook.yml
2. 需要重新部署ape_sqs ,即执行 ansible-playbook --connection=local  -i  localhost, -u ec2-user  --tags "ape_sqs" ape_playbook.yml

# ec2 inventory 增加按集群分组
1. 执行 ansible-inventory -i aws_ec2.yml --graph ,可以看到按集群id分的组，如果部署时直接复制此分组ID，将会部署集群中的所有类型机器[`master`,`core`,`task`],注意这很危险，因为jmx部署会重启master上NameNode和ResourceManager。
```

##### 2021-07-02

`relable 怎么配置`

```yaml
global:
  evaluation_interval: 15s
  scrape_interval: 15s
  scrape_timeout: 10s
scrape_configs:
  - consul_sd_configs:
    - server: localhost:8500
    job_name: consul_sd
    relabel_configs:
     - source_labels:
       - __meta_consul_tags
       regex: ^\,([^\.]+)\,([^\.]+)\,([^\.]+)\,$
       replacement: "${1}"
       target_label: cluster_id
     - source_labels:
       - __meta_consul_tags
       regex: ^\,([^\.]+)\,([^\.]+)\,([^\.]+)\,$
       replacement: "${2}"
       target_label: cluster_name
     - source_labels:
       - __meta_consul_tags
       regex: ^\,([^\.]+)\,([^\.]+)\,([^\.]+)\,$
       replacement: "${3}"
       target_label: exporter_name
```

`结果是什么样`

![](https://pcmyp.oss-accelerate.aliyuncs.com/markdown/20210701225905.png)

##### 2021-07-01

```
1. boto3 api rate limit,采用adaptive retry mode
2. consul meta tags 包含集群ID，名称 ，exporter名称 用于relable
3. hadoop3.x , 2.x datanode port 检查切换(3.x 9866, 2.x 50010)
```



#### 一、背景

`给客户的文档一般都是将当前文档转换为PDF交给客户，因此这里的文档更新,可能不会及时同步到客户，客户可以在这里看到最新文档说明, 客户部署时按照这里文档说明部署即可`

##### 1.1 基本说明

客户希望使用`Prometheus+Grafana`对EMR集群进行监控，经过沟通确定了使用`node_exporter`和`jmx_exporter`两个组件上报相关Metrics。需要解决的问题是如何自动化部署监控服务和exporter，同时希望该部署方案对当前客户`已运行EMR集群`的Instance以及在集群`Resize过程`中产生的Instance都能适配。

##### 1.2 实现目标

1. 一键自动部署Prometheus+Grafana+Consul服务
2. 一键自动部署`expoter`到已运行的Instance
3. Lambda事件触发自动部署`expoter`到`Resize`过程产生的Instance
4. `exporter`部署完毕后，自动更新到`Prometheus`配置
5. `jmx_exporter` 可选择部署到`Namenode,Datanode,ResourceManager,Nodemanager`四个JAVA进程中
6. 支持`node_exporter`和`jmx_exporter`版本更新

##### 1.3 部署架构

* 注意这张图描述的是Ansible的部署服务基本图示，非详细的数据流转图示

<img src="https://pcmyp.oss-accelerate.aliyuncs.com/markdown/20210605005204.png" style="zoom:50%;" />

#### 二、部署说明

##### 2.1 前置条件

```markdown
#  EC2[Amazon Linux 2 RMI]一台， 作用如下:
1. 在该EC2上安装Promtheus和Grafana
2. 在该EC2上安装Ansible，通过ssh部署node_exporter和jmx_exporterd到EMR集群

# 权限
1. EC2(ansible这台机器，非ERM机器)需要的权限运行task权限会自动添加(自动添加EMR机器所需要权限)，`需要注意的是，你使用的的aws用户，至少要有以下权限`
"iam:CreatePolicy",
"iam:ListPolicies",
"iam:CreateInstanceProfile",
"iam:PassRole",
"iam:CreateRole",
"iam:AttachRolePolicy",
"iam:AddRoleToInstanceProfile",
"ec2:AssociateIamInstanceProfile"

2. 如果EC2(ansible这台机器，非ERM机器)上已经有Role，则不会修改权限。需要你手动在该EC2上加入权限，权限列表如下
"ec2:DeleteTags",
"ec2:CreateTags",
"ec2:Describe*",
"sqs:Get*",
"sqs:List*",
"elasticmapreduce:Describe*",
"elasticmapreduce:List*"

`EC2和EMR集群内网可通`
```

##### 2.2 代码说明

方案是通过Ansible实现的，代码开发完毕，在GitHub上，[点击查看]( https://github.com/yhyyz/ansible-prometheus-exporter.git)。这里相对代码结构做一个简单说明。

```yml
├── ansible-prometheus-exporter   # 项目名称
│   ├── keys                     # 存放ssh key 的目录，里面两个空文件，把你的多个key放在此目录下
│   ├── ansible.cfg              # ansibl 的全局配置文件
│   ├── ape_playbook.yml         # ape[项目名称简写], 这个是部署Prometheus+Grafana+ape自身服务
│   ├── aws_ec2.yml							 # 动态EC2 Inventory, 可以动态获取要部署的Instance
│   ├── exporter_playbook.yml    # 自动部署 node_exporter 和jmx_exporter
│   ├── exporter_resize_playbook.yml    # 为emr resize 出来的节点自动部署 node_exporter 和jmx_exporter
│   ├── autometa_playbook.yml    # 自动生成meta.json文件的任务
│   ├── roles                    # 将各个模块，以Ansible Role的方式封装
│   │   ├── ape_sqs          # 集群Resize过程，触发Lambda消息发送到SQS,该服务消费SQS,安exporter
│   │   ├── cloudalchemy.grafana # 在EC2安装Grafana，开源提供
│   │   ├── ansible-consul #  在EC2安装Consul，开源提供
│   │   ├── cloudalchemy.prometheus # 在EC2安装Prometheus，开源提供
│   │   ├── jmx_exporter    # 部署jmx_exporter到EMR
│   │   └── node_exporter   # 部署node_exporter到EMR
│   ├── get_key.sh           # 根据集群名字，从meta获取ssh key
│   ├── gen_meta_role.py     # 生成meta.json的脚本，同时会为部署添加相关IAM权限
│   ├── meta.json           # 里面是配置信息，将EMR多个集群信息在这里配置
│   └── reg_sd.py    #  exporter 安装完毕后触发更新Prometheus的scrape, 默认是注册到consul服务发现
```

##### 2.3 Ansible 安装

```shell
# 在你启动的EC2上安装Ansible，注意在安装之前，给EC2相应的权限，这在前置条件中已经说明。 执行如下命令安装即可
# 登陆到EC2, 我这里默认在/home/ec2-user下,
sudo yum install python3

# create venv 虚拟环境
python3 -m venv ansible_venv
# 激活虚拟环境
source ./ansible_venv/bin/activate
# 安装ansible 和boto3
pip install ansible
pip install boto3
pip install requests
```

##### 2.4 代码下载及配置

```shell
# 下载代码
sudo yum install -y  git
git clone https://github.com/yhyyz/ansible-prometheus-exporter.git
cd ansible-prometheus-exporter

# 配置aws_ec2.yml
# 这里面只需要配置一个参数Regions即可，默认是 ap-southeast-1, 可以执行如下命令替换,注意命令中修改为你自己的信息, 当然也可以vi 打开文件进行修改
sed -i  's/ap-southeast-1/your-region/g' aws_ec2.yml

# 将你访问的emr集群ssh key, 放到keys目录中，注意修改权限为500. 需要注意的是如果meta信息是自动生成的，对于每个emr集群的key的名字，是通过API从EMR集群配置上获取的，请确保你的key和集群配置的key名字一致。
```

##### 2.5 部署APE

```shell
# 执行命令部署Prometheus ,Grafana,Consul, ape_sqs
ansible-playbook --connection=local  -i  localhost, -u ec2-user ape_playbook.yml

# 下面的命令是根据tag按照服务单个执行
ansible-playbook --connection=local  -i  localhost, -u ec2-user  --tags "ape_prometheus"    ape_playbook.yml
ansible-playbook --connection=local  -i  localhost, -u ec2-user  --tags "ape_grafana"    ape_playbook.yml
ansible-playbook --connection=local  -i  localhost, -u ec2-user  --tags "ape_consul" ape_playbook.yml
ansible-playbook --connection=local  -i  localhost, -u ec2-user  --tags "ape_sqs" ape_playbook.yml

# 执行完之后，服务就完整完成，并启动，直接访问即可 1. grafana 端口3000，用户名密码都是：admin， 第一此访问需要你修改密码。 2. pometheus web端口9090 3. ape_sqs服务会通过systemed启动。 可通过命令检查一下
sudo systemctl status prometheus
sudo systemctl status grafana-server
sudo systemctl status consul
sudo systemctl status ape_sqs
```

##### 2.6 部署Exporter

```shell
# 执行如下命令自动生成meta配置，执行后会让你输入相关参数值，其中参数已有默认值，如果不改变直接回车即可。 之后会列出所有的集群名字，让你输入要部署的集群名字，输入后回车即可，该playbook执行完毕后，会自动生成meta.json，权限也会自动配置好。同时会生成一个extra_vars.yml文件，这个文件中变量信息会提供给exporter_playbook.yml使用。 注意部署不同的集群请重新执行下面命令。
ansible-playbook --connection=local  -i  localhost, -u ec2-user  atuometa_playbook.yml

# 执行如下命令可以查看到你现有的集群实例
ansible-inventory -i aws_ec2.yml --graph
# 上述命令的输出结果类似如下, 下面地址有公网显示公网，无公网显示私网，无论显示什么，在ssh连接时配置中指定的是私网连接
@all:
  |--@aws_ec2:
  |  |--172.31.0.182
  |  |--172.31.1.215
  |  |--172.31.14.235
  |  |--172.31.2.97
  |  |--172.31.3.16
  |--@emr_flow_role___j_KO4KLWAKC4GZ____CORE__:
  |  |--172.31.0.182
  |  |--172.31.14.235
  |--@emr_flow_role___j_KO4KLWAKC4GZ____MASTER__:
  |  |--172.31.2.97
  |--@emr_flow_role___j_KO4KLWAKC4GZ____TASK__:
  |  |--172.31.1.215
  |  |--172.31.3.16
  |--@ungrouped:

# 执行如下命令可以向节点部署node_exporter和jvm_exporter, 该命令中注意 --limit 参数的值，就是上述命令输出结果的@之后的值， 这其实是给集群安装CORE，MASTER，TASK 节点分了组，执行安装命令是可以按组安装，也可以指定单台机器按照。 最好先指定单台机器按照，一切OK，再按组批量安装。

# 单台机器安装， 注意ip后的逗号不能省略
ansible-playbook -i  172.31.3.16, -u hadoop  exporter_playbook.yml

# 按Tag 分组安装命令如下，注意替换limit的值，为你自己的值，最好先执行单台安装测试
# 需要强调的是，jmx exporter的部署是需要重启JVM进程的，尤其Master节点上的Namenode进程和ResourceManager进程重启，你的集群会处于不可用状态。
ansible-playbook -i aws_ec2.yml -u hadoop  --limit     emr_flow_role___j_KO4KLWAKC4GZ____TASK__ exporter_playbook.yml

# 安装执行完毕后，可以通过如下命令测试
# node_exporter metrics
curl 172.31.3.16:9100/metrics
#jmx exporter , namenode,datanode,resourcemanager,nodemanager 四个服务exporter端口默认分别是7005，7006，7007，7008, 根据你节点服务同步，选择端口测试即可
curl 172.31.3.16:7008/metrics
# consul 服务发现，可以通过下面API，查看已安装的服务在consul中是否成功注册，同时consul在Prometheus中也已自动配置，相关的tag已经打到了consul的service tag中
curl http://localhost:8500/v1/catalog/service/node_exporter  |jq .
curl http://localhost:8500/v1/catalog/service/jmx_exporter_nm |jq .
curl http://localhost:8500/v1/catalog/service/jmx_exporter_dn |jq .
curl http://localhost:8500/v1/catalog/service/jmx_exporter_rm |jq .
curl http://localhost:8500/v1/catalog/service/jmx_exporter_nm |jq .

```

##### 2.7 查看Metrics

```markdown
# 经过以上步骤，服务就全部安装完毕了，可以去Grafana查看了。
# node_exporter,jmx_exporter指标数据都已经在Prometheus中了，你可以在Grafan按需配置你自己的图表了。 你也可以加载开源的别人配置好图表。比如这里就在Grafana加载了如下ID图表
node_exporter  ID: 1860  URL: https://grafana.com/grafana/dashboards/1860
jmx_exporter  根据你的Metrics需求在Grafana上配置即可

`一些dashboards已经预置到Grafana中了，直接访问grafana web界面，http://your-ec2-ip:3000/dashboards 就可以看到所有预制模板，`

```

##### 2.8 Resize Instance

对于Resize实例的expoter安装，是通过EMR的CloudWatchEvent触发Lamaba， Lambda中将集群的状态改变的Event发到SQS即可。 这个配置很简单，只把步骤列在下面，不做过多说明了，同时Lamada的代码放到下面

1. 创建一个SQS，用来接收Lambad发送的EMR Event， SQS的Queue选择`FIFO`，注意开启ContentBasedDeduplication，名字就写你在2.4小结中配置的名字

2. 创建一个lambda函数，函数内容如下

   ```python
   import json
   import boto3

   def lambda_handler(event, context):
       json_str = json.dumps(event)
       sqs = boto3.resource('sqs')
       queue = sqs.get_queue_by_name(QueueName='emr-state-queue.fifo')
       # MessageGroupId only to FIFO
       response = queue.send_message(MessageBody=json_str,MessageGroupId="state-group-01")
       return json.dumps(response)
   ```

3. 在Cloudwatch中选择EME Event, 选择状态更改发送到这个Lambda即可

#### 三、部署图示

##### 3.1 APE部署图示(部分截图)

![](https://pcmyp.oss-accelerate.aliyuncs.com/markdown/20210605005054.png)

![](https://pcmyp.oss-accelerate.aliyuncs.com/markdown/20210605005126.png)

##### 3.2 Exporter 部署图示(部分截图)

![](https://pcmyp.oss-accelerate.aliyuncs.com/markdown/20210605013553.png)

![](https://pcmyp.oss-accelerate.aliyuncs.com/markdown/20210605021108.png)

##### 3.3 Metrics(部分截图)

![](https://pcmyp.oss-accelerate.aliyuncs.com/markdown/20210605020120.png)

![](https://pcmyp.oss-accelerate.aliyuncs.com/markdown/20210605020302.png)

![](https://pcmyp.oss-accelerate.aliyuncs.com/markdown/20210605020857.png)

#### 四、特别说明

```markdown
1. 以上部署测试ERM版本为 5.33.0， 其它ERM版本未测试，使用时请根据版本测试
2. 以上部署方案只是和客户探讨沟通的解决方案，方案实施是需要客户做根据环境做进一步测试和调整的，不能不经过测试，直接就上生产环境。
3. 当前代码只是V1版本，可根据客户测试及使用，双方共同解决BUG及功能升级。
4. 再次强调，对应jmx_exporter的安装是会自动重启JVM的，node_exporter不影响集群服务。

