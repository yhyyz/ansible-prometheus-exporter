# -*- coding: UTF-8 -*-
import boto3
import json
import time
import sys

global aws_region
def gen_exporter_instance_sd(exporter_tag,tag_value,ip_type, cluster_id):
    ec2_client = boto3.client('ec2',region_name=aws_region)
    ip_list = []
    ec2_response = ec2_client.describe_instances(
        Filters=[
            {
                'Name': 'tag:'+exporter_tag,
                'Values': [tag_value]
            },
            {
                'Name': 'tag:aws:elasticmapreduce:job-flow-id',
                'Values': [cluster_id]
            },
        ],
    )
    for reserv in ec2_response["Reservations"]:
        instances_list = reserv["Instances"]
        for ins in instances_list:
           ip_list.append(ins[ip_type])
    return ip_list


def format_sd(metrics,job):
    file_sd = {}
    file_sd["targets"] = metrics
    labels = {}
    labels["job"] = job
    labels["cluster"] = cluster_id
    file_sd["labels"] = labels
    return file_sd


def gen_node_jmx_sd(ip_type,cluster_id):
    sd_list = []
    node_ip_list = gen_exporter_instance_sd("node_exporter","installed",ip_type, cluster_id)
    if len(node_ip_list)>0:
        node_sd_metric = [x + ":9100" for x in node_ip_list]
        node_file_sd = format_sd(node_sd_metric,"node_exporter")
        sd_list.append(node_file_sd)

    jmx_nn_sd = gen_exporter_instance_sd("jmx_exporter_nn","installed",ip_type, cluster_id)
    if len(jmx_nn_sd)>0:
        jmx_nn_metric = [x + ":7005" for x in jmx_nn_sd]
        nn_file_sd = format_sd(jmx_nn_metric,"jmx_exporter_nn")
        sd_list.append(nn_file_sd)


    jmx_dn_sd = gen_exporter_instance_sd("jmx_exporter_dn", "installed", ip_type, cluster_id)
    if len(jmx_dn_sd) >0:
        jmx_dn_metric = [x + ":7006" for x in jmx_dn_sd]
        dn_file_sd = format_sd(jmx_dn_metric, "jmx_exporter_dn")
        sd_list.append(dn_file_sd)


    jmx_rn_sd = gen_exporter_instance_sd("jmx_exporter_rn", "installed", ip_type, cluster_id)
    if len(jmx_rn_sd) > 0:
        jmx_rn_metric = [x + ":7007" for x in jmx_rn_sd]
        rn_file_sd = format_sd(jmx_rn_metric, "jmx_exporter_rn")
        sd_list.append(rn_file_sd)

    jmx_nm_sd = gen_exporter_instance_sd("jmx_exporter_nm", "installed", ip_type, cluster_id)
    if len(jmx_nm_sd) > 0:
        jmx_nm_metric = [x + ":7008" for x in jmx_nm_sd]
        nm_file_sd = format_sd(jmx_nm_metric, "jmx_exporter_nm")
        sd_list.append(nm_file_sd)
    return sd_list


def write_sd_file(prometheus_sd_dir,cluster_id,sd_str):
    write_time= time.strftime("%Y%m%d%H%M%S", time.localtime())
    file_name=prometheus_sd_dir+"/"+cluster_id+"-"+write_time+".json"
    with open(file_name,"w") as f:
        f.write(sd_str)


if __name__ == '__main__':
    aws_region = sys.argv[1]
    cluster_id = sys.argv[2]
    ip_type = sys.argv[3]
    prometheus_sd_dir = sys.argv[4]
    # sleep 3s ,get jmx tag as much as possible
    time.sleep(3)
    sd_list = gen_node_jmx_sd(ip_type, cluster_id)
    if len(sd_list) > 0:
        sd_str = json.dumps(sd_list)
        write_sd_file(prometheus_sd_dir,cluster_id,sd_str)



