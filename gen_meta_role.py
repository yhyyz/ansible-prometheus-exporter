# -*- coding: UTF-8 -*-
import boto3
from botocore.exceptions import ClientError
import json
import argparse
import requests
import os

from botocore.config import Config

config = Config(
   retries={
      'max_attempts': 100,
      'mode': 'adaptive'  # adaptive standard
   }
)

def get_emr_cluster_meta(aws_region, ssh_user, ip_type, prometheus_sd_dir, consul_address, sqs_queue_name):
    client = boto3.client('emr', config=config,region_name=aws_region)
    paginator = client.get_paginator('list_clusters')
    clusters_resp = paginator.paginate(
        ClusterStates=[
            'WAITING'
        ],
        PaginationConfig={
            'MaxItems': 5000,
        }
    )
    cluster_list = []
    for page in clusters_resp:
        for cluster in page["Clusters"]:
            cluster_id = cluster["Id"]
            cluster_name = cluster["Name"]
            describe_response = client.describe_cluster(
                ClusterId=cluster_id
            )
            keyName = describe_response["Cluster"]["Ec2InstanceAttributes"]["Ec2KeyName"]
            ServiceRole = describe_response["Cluster"]["ServiceRole"]
            cluster_info = {"cluster_id": cluster_id,
                            "cluster_name": cluster_name,
                            "private_key": keyName + ".pem",
                            "ssh_user": ssh_user,
                            "ip_type": ip_type,
                            "prometheus_sd_dir": prometheus_sd_dir,
                            "consul_address": consul_address,
                            "service_role": ServiceRole
                            }
            cluster_list.append(cluster_info)
    project_path = os.path.split(os.path.realpath(__file__))[0]
    meta = {"base": cluster_list, "aws_region": aws_region, "sqs_queue_name": sqs_queue_name,"project_path": project_path}
    return meta


def write_meta_file(meta):
    with open("meta.json", "w") as f:
        f.write(json.dumps(meta))

def create_emr_ec2_policy():
    ec2_tags_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": [
                    "ec2:DeleteTags",
                    "ec2:DescribeTags",
                    "ec2:CreateTags",
                    "ec2:Describe*"
                ],
                "Resource": "*"
            }
        ]
    }
    client = boto3.client('iam',config=config)
    try:
        response = client.create_policy(
            PolicyName='ansible_ec2_tag',
            Path="/ansible/ec2/",
            PolicyDocument=json.dumps(ec2_tags_policy),
            Description='ansible ec2 create tag policy'
        )
        # print(response)
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            print("ansible_ec2_tag policy already created")
        else:
            print("Unexpected error: %s" % e)


def attach_role_policy_to_cluster(cluster_meta):
    client = boto3.client('iam',config=config)
    ansible_ec2_tag_policy = client.list_policies(
        Scope='All',
        OnlyAttached=False,
        PathPrefix='/ansible/ec2/',
    )
    arn = ansible_ec2_tag_policy["Policies"][0]["Arn"]
    for cluster in cluster_meta["base"]:
        role = cluster["service_role"]
        response = client.attach_role_policy(
            RoleName=role,
            PolicyArn=arn
        )
        # print(response)


def create_ansilbe_master_policy(aws_region):
    client = boto3.client('iam',config=config)
    ansilbe_master_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": [
                    "ec2:DeleteTags",
                    "ec2:DescribeTags",
                    "ec2:CreateTags",
                    "ec2:Describe*",
                    "sqs:GetQueueAttributes",
                    "sqs:GetQueueUrl",
                    "sqs:ListDeadLetterSourceQueues",
                    "sqs:ListQueues",
                    "elasticmapreduce:DescribeCluster",
                    "elasticmapreduce:DescribeEditor",
                    "elasticmapreduce:DescribeJobFlows",
                    "elasticmapreduce:DescribeSecurityConfiguration",
                    "elasticmapreduce:DescribeStep",
                    "elasticmapreduce:GetBlockPublicAccessConfiguration",
                    "elasticmapreduce:GetManagedScalingPolicy",
                    "elasticmapreduce:ListBootstrapActions",
                    "elasticmapreduce:ListClusters",
                    "elasticmapreduce:ListEditors",
                    "elasticmapreduce:ListInstanceFleets",
                    "elasticmapreduce:ListInstanceGroups",
                    "elasticmapreduce:ListInstances",
                    "elasticmapreduce:ListSecurityConfigurations",
                    "elasticmapreduce:ListSteps",
                    "elasticmapreduce:ViewEventsFromAllClustersInConsole"
                ],
                "Resource": "*"
            }
        ]
    }
    try:
        response = client.create_policy(
            PolicyName='ansible_master',
            Path="/ansible/master/",
            PolicyDocument=json.dumps(ansilbe_master_policy),
            Description='ansible master policy create tag policy'
        )
        print(response)
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            print("ansible_master policy already created")
        else:
            print("Unexpected error: %s" % e)

    assume_role = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "ec2.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    print("create ansible master role")
    try:
        create_role_response = client.create_role(
            RoleName="ansible_master_role",
            AssumeRolePolicyDocument=json.dumps(assume_role)
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            print("ansible_master_role  already created")
        else:
            print("Unexpected error: %s" % e)

    ansible_master_policy = client.list_policies(
        Scope='All',
        OnlyAttached=False,
        PathPrefix='/ansible/master/',
    )
    arn = ansible_master_policy["Policies"][0]["Arn"]

    print("attach ansible_master_role policy")
    attach_role_response = client.attach_role_policy(
        RoleName="ansible_master_role",
        PolicyArn=arn
    )

    print("create instance profile ansible_deploy_profile")
    try:
        instance_profile = client.create_instance_profile(
            InstanceProfileName='ansible_deploy_profile',
            Path='/ansilbe/profile/',
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            print("ansible_deploy_profile  already created")
        else:
            print("Unexpected error: %s" % e)

    print("add ansible_master_role profile ansible_deploy_profile")

    try:
        role_to_profile_response = client.add_role_to_instance_profile(
            InstanceProfileName='ansible_deploy_profile',
            RoleName='ansible_master_role'
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'LimitExceeded':
            print("add_role_to_instance_profile  already exec")
        else:
            print("Unexpected error: %s" % e)

    print("associate ansible_deploy_profile to instance")
    res = requests.get("http://169.254.169.254/latest/meta-data/instance-id")
    instance_id = res.text
    ec2_client = boto3.client('ec2',config=config,region_name=aws_region)
    try:
        response = ec2_client.associate_iam_instance_profile(
            IamInstanceProfile={
                # 'Arn': 'string',
                'Name': 'ansible_deploy_profile'
            },
            InstanceId=str(instance_id)
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'IncorrectState':
            print("existing association for instance")
        else:
            print("Unexpected error: %s" % e)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Please input params')
    parser.add_argument("-a", "--aws_region", default="ap-southeast-1")
    parser.add_argument("-s", "--ssh_user", default="hadoop")
    parser.add_argument("-i", "--ip_type", default="PrivateIpAddress")
    parser.add_argument("-p", "--prometheus_sd_dir", default="")
    parser.add_argument("-c", "--consul_address", default="http://localhost:8500/v1/agent/service/register" )
    parser.add_argument("-q", "--sqs_queue_name", default="emr-state-queue.fifo")
    args = parser.parse_args()
    # print(args)
    print("gen cluster meta")
    cluster_meta = get_emr_cluster_meta(args.aws_region, args.ssh_user, args.ip_type,
                                        args.prometheus_sd_dir, args.consul_address, args.sqs_queue_name)
    print("write meta.json file")
    write_meta_file(cluster_meta)
    print("create policy ansible_ec2_tag")
    create_emr_ec2_policy()
    print("attach role to cluster")
    attach_role_policy_to_cluster(cluster_meta)
    print("create role ansible master")
    create_ansilbe_master_policy(args.aws_region)

