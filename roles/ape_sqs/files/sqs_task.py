# -*- coding: UTF-8 -*-
import boto3
import json
from ansible.cli.playbook import PlaybookCLI
import traceback
import os
import sys
global aws_region
import time

def event_handler(event,exec_exporter_user,private_key_file):
    is_ok = False
    try:
        if is_resize_complete(event):
            cluster_id = event['detail']["clusterId"]
            untaged_ins = get_untaged_instances(cluster_id)
            if len(untaged_ins) == 0:
                print("no untaged instance")
                return True
            hosts = ",".join(untaged_ins)+","
            print("untaged host: {0}".format(hosts))
            cli = PlaybookCLI([" ", '-i', hosts, '-u', exec_exporter_user, '--private-key', private_key_file, "exporter_playbook.yml"])
            results = cli.run()
            if results == 0:
                is_ok = True
                print("ansible install exporter ok")
            else:
                print("ansible install exporter error")
        else:
            print("ERM State Change resize not complete.")
    except Exception as error:
        print("ape run error: ", error)
        # traceback.print_exc()
    return is_ok


def is_resize_complete(event):
    if (event['detail-type'] == "EMR Instance Group State Change"
        or event['detail-type'] == "EMR Instance Fleet State Change") \
            and "is complete" in event['detail']["message"] \
            and event['detail']["state"] == "RUNNING":
        return True
    else:
        return False


def get_untaged_instances(cluster_id):
    emr_client = boto3.client('emr',region_name=aws_region)
    response = emr_client.describe_cluster(
        ClusterId=cluster_id
    )
    untaged_list = []
    if response["Cluster"]["InstanceCollectionType"] == "INSTANCE_GROUP":
        emr_response = emr_client.list_instances(
            ClusterId=cluster_id,
            InstanceGroupTypes=['CORE', 'TASK'],
            InstanceStates=[
                'RUNNING'
            ],
        )
        untaged_list.extend(filter_instance(emr_response))

    if response["Cluster"]["InstanceCollectionType"] == "INSTANCE_FLEET":
        emr_response_task = emr_client.list_instances(
            ClusterId=cluster_id,
            InstanceFleetType='TASK',
            InstanceStates=[
                'RUNNING'
            ],
        )
        untaged_list.extend(filter_instance(emr_response_task))
        emr_response_core = emr_client.list_instances(
            ClusterId=cluster_id,
            InstanceFleetType='CORE',
            InstanceStates=[
                'RUNNING'
            ],
        )
        untaged_list.extend(filter_instance(emr_response_core))
    return list(set(untaged_list))


def filter_instance(emr_instances):
    ec2_client = boto3.client('ec2',region_name=aws_region)
    ins_list = []
    ins_dict = {}
    for ins in emr_instances["Instances"]:
        pubIP = ins["PublicIpAddress"]
        ec2ID = ins["Ec2InstanceId"]
        # ins["PrivateIpAddress"]
        ins_list.append(ec2ID)
        ins_dict[ec2ID] = pubIP
    ec2_response = ec2_client.describe_tags(
        Filters=[
            {
                'Name': 'resource-id',
                'Values': ins_list
            }
        ],
    )
    untag_list = []
    for tag in ec2_response["Tags"]:
        if tag["Key"] == "node_exporter" or tag["Key"] == "jmx_exporter_nn" \
                or tag["Key"] == "jmx_exporter_dn" \
                or tag["Key"] == "jmx_exporter_rn" \
                or tag["Key"] == "jmx_exporter_nm":
            ec2_id = tag["ResourceId"]
            ins_dict[ec2_id]=""

    for key, value in ins_dict.items():
        if value != "":
            untag_list.append(value)
    return list(set(untag_list))


def process_msg(sqs_queue_name, exec_exporter_user, private_key_file):
    sqs = boto3.resource('sqs',region_name=aws_region)
    while 1:
        try:
            queue = sqs.get_queue_by_name(QueueName=sqs_queue_name)
            if queue != None:
                break
        except Exception as error:
            print("queue is not  ok, after 15s retry ... ", error)
            time.sleep(15)
    while 1:
        # print("wait message")
        for message in queue.receive_messages(AttributeNames=["All"],MaxNumberOfMessages=3, WaitTimeSeconds=5):
            # Get the custom author message attribute if it was set
            try:
                print(message.body)
                event = json.loads(message.body)
                # print(event)
                res = event_handler(event,exec_exporter_user,private_key_file)
                if res:
                    print("delete msg")
                    message.delete()
            except Exception as error:
                print("process sqs  error: ", error)


if __name__ == '__main__':
    aws_region = sys.argv[1]
    sqs_queue_name = sys.argv[2]
    exec_exporter_user = sys.argv[3]
    private_key_file = sys.argv[4]
    process_msg(sqs_queue_name,exec_exporter_user, private_key_file)