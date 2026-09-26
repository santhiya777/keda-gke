# Event-driven autoscaling with KEDA in GKE

This repository contains the sample application and template files used in the article [Event-Driven Autoscaling in Kubernetes: Harnessing the Power of KEDA](https://www.doit.com/event-driven-autoscaling-in-kubernetes-harnessing-the-power-of-keda/) published on Medium.

## Overview
The purpose of this repository is to provide a reference implementation for event-driven autoscaling in Kubernetes using KEDA. It includes a sample application and the necessary template files to demonstrate the concepts discussed in the article.

## Contents

- `app/`: Contains the source code and configuration files for the sample application.
- `templates/`: Includes the Kubernetes manifest templates for deploying the application and configuring autoscaling with KEDA.
- `generate-message.sh`: A small load generator that publishes a message to the Pub/Sub topic every second, used to trigger and observe autoscaling.

## Prerequisites

- A GKE cluster with Workload Identity enabled
- [kubectl](https://kubernetes.io/docs/tasks/tools/) and [Helm](https://helm.sh/docs/intro/install/) installed locally or in your CI/CD setup
- The `gcloud` CLI, authenticated and configured for your target GCP project

## Setup Pub/Sub resources

Run the below commands to set up a Pub/Sub topic and subscription.

```bash
GCP_PROJECT_ID=$(gcloud config get-value project)
TOPIC_NAME=keda-demo-topic
SUBSCRIPTION_NAME=keda-demo-topic-subscription

# Create Topic
gcloud pubsub topics create $TOPIC_NAME --project $GCP_PROJECT_ID

# Create Subscription
gcloud pubsub subscriptions create $SUBSCRIPTION_NAME \
  --topic $TOPIC_NAME \
  --project $GCP_PROJECT_ID
```

## Setup Workload Identity for KEDA

[GCP Workload Identity](https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity) allows workloads in GKE clusters to impersonate Identity and Access Management (IAM) service accounts to access Google Cloud services. Workload Identity is the recommended way for workloads running on GKE to access Google Cloud services in a secure and manageable way.

Run the below commands to set up Workload Identity for KEDA.

```bash
KEDA_GCP_SERVICE_ACCOUNT=keda-operator
KEDA_NAMESPACE=keda
KEDA_K8S_SERVICE_ACCOUNT=keda-operator

# Create GCP service account
gcloud iam service-accounts create $KEDA_GCP_SERVICE_ACCOUNT \
  --project=$GCP_PROJECT_ID

# Create IAM role bindings
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
  --member "serviceAccount:$KEDA_GCP_SERVICE_ACCOUNT@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --role "roles/monitoring.viewer"

# Allow the Kubernetes service account to impersonate the GCP service account
gcloud iam service-accounts add-iam-policy-binding $KEDA_GCP_SERVICE_ACCOUNT@$GCP_PROJECT_ID.iam.gserviceaccount.com \
  --role roles/iam.workloadIdentityUser \
  --member "serviceAccount:$GCP_PROJECT_ID.svc.id.goog[$KEDA_NAMESPACE/$KEDA_K8S_SERVICE_ACCOUNT]"
```

## Install KEDA

Below are the various options for installing KEDA on a Kubernetes cluster:

- [Helm charts](https://keda.sh/docs/2.10/deploy/#helm)
- [OperatorHub](https://keda.sh/docs/2.10/deploy/#operatorhub)
- [YAML declarations](https://keda.sh/docs/2.10/deploy/#yaml)

We will use the Helm chart to deploy KEDA in the GKE cluster.

Add and update the Helm repo:

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
```

Install the latest KEDA Helm chart:

```bash
helm upgrade --install keda kedacore/keda \
  --namespace keda \
  --set 'serviceAccount.annotations.iam\.gke\.io\/gcp-service-account'="$KEDA_GCP_SERVICE_ACCOUNT@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --create-namespace \
  --debug \
  --wait
```

The KEDA webhook calls are served over port 9443, so ensure any firewall rule between the control plane and the nodes allows requests over that port. In GKE, the auto-generated firewall rules only allow communication over ports 443 and 10250, so you'll need to create a new firewall rule to allow traffic over port 9443.

Sample `gcloud` firewall rule command:

```bash
gcloud compute firewall-rules create allow-api-server-to-keda-webhook \
  --description="Allow Kubernetes API server to call the KEDA webhook on worker nodes over TCP port 9443" \
  --direction=INGRESS \
  --priority=1000 \
  --network=$VPC_NETWORK_NAME \
  --action=ALLOW \
  --rules=tcp:9443 \
  --source-ranges=$CONTROL_PLANE_IP_RANGE \
  --target-tags=$NETWORK_TAGS_ASSIGNED_TO_NODES
```

## Deploy the sample application

Set up Workload Identity for the sample application so it can consume messages from the Pub/Sub subscription.

```bash
SAMPLE_APP_GCP_SERVICE_ACCOUNT=keda-demo
SAMPLE_APP_NAMESPACE=default
SAMPLE_APP_K8S_SERVICE_ACCOUNT=keda-demo

# Create GCP service account
gcloud iam service-accounts create $SAMPLE_APP_GCP_SERVICE_ACCOUNT \
  --project=$GCP_PROJECT_ID

# Create IAM role bindings
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
  --member "serviceAccount:$SAMPLE_APP_GCP_SERVICE_ACCOUNT@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --role "roles/pubsub.subscriber"

# Allow the Kubernetes service account to impersonate the GCP service account
gcloud iam service-accounts add-iam-policy-binding $SAMPLE_APP_GCP_SERVICE_ACCOUNT@$GCP_PROJECT_ID.iam.gserviceaccount.com \
  --role roles/iam.workloadIdentityUser \
  --member "serviceAccount:$GCP_PROJECT_ID.svc.id.goog[$SAMPLE_APP_NAMESPACE/$SAMPLE_APP_K8S_SERVICE_ACCOUNT]"
```

Deploy the sample application to the GKE cluster:

```bash
cat <<EOF | kubectl apply -f -
---
apiVersion: v1
kind: ServiceAccount
metadata:
  annotations:
    iam.gke.io/gcp-service-account: keda-demo@$GCP_PROJECT_ID.iam.gserviceaccount.com
  name: keda-demo
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keda-demo
spec:
  selector:
    matchLabels:
      app: keda-demo
  replicas: 1
  template:
    metadata:
      labels:
        app: keda-demo
    spec:
      serviceAccountName: keda-demo
      containers:
      - image: simbu1290/keda-demo:v1
        name: consumer
        env:
        - name: PUB_SUB_PROJECT
          value: $GCP_PROJECT_ID
        - name: PUB_SUB_TOPIC
          value: "keda-demo-topic"
        - name: PUB_SUB_SUBSCRIPTION
          value: "keda-demo-topic-subscription"
EOF
```

## Deploy the KEDA event scaler

KEDA seamlessly integrates with various [scalers](https://keda.sh/docs/2.10/scalers/) (event sources) and uses Custom Resource Definitions (CRDs) to specify the desired scaling behavior and parameters. KEDA monitors the event source and feeds that data to the Horizontal Pod Autoscaler (HPA) to drive rapid scaling of a resource.

Here we use the [GCP Pub/Sub](https://keda.sh/docs/2.10/scalers/gcp-pub-sub/) event scaler to demonstrate autoscaling. The scaling relationship between an event source and a specific workload (e.g., Deployment, StatefulSet) is configured using the [ScaledObject](https://keda.sh/docs/2.10/concepts/scaling-deployments/#scaledobject-spec) Custom Resource Definition.

[TriggerAuthentication](https://keda.sh/docs/2.10/concepts/authentication/#re-use-credentials-and-delegate-auth-with-triggerauthentication) lets you describe authentication parameters separately from the `ScaledObject` and the deployment containers. It also enables more advanced authentication methods like pod identity and credential re-use.

Deploy the resources below for autoscaling — KEDA will scale based on the number of unacknowledged messages in the subscription.

```bash
cat <<EOF | kubectl apply -f -
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: keda-demo-trigger-auth-gcp-credentials
spec:
  podIdentity:
    provider: gcp
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: keda-demo-pubsub-scaledobject
spec:
  scaleTargetRef:
    apiVersion: apps/v1 # Optional. Default: apps/v1
    kind: Deployment    # Optional. Default: Deployment
    name: keda-demo     # Mandatory. Must be in the same namespace as the ScaledObject
  pollingInterval: 5    # Optional. Default: 30 seconds
  minReplicaCount: 0    # Optional. Default: 0
  maxReplicaCount: 10   # Optional. Default: 100
  triggers:
  - type: gcp-pubsub
    authenticationRef:
      kind: TriggerAuthentication
      name: keda-demo-trigger-auth-gcp-credentials
    metadata:
      mode: "SubscriptionSize" # Optional - Default is SubscriptionSize - SubscriptionSize or OldestUnackedMessageAge
      value: "5" # Optional - Default is 5 for SubscriptionSize | Default is 10 for OldestUnackedMessageAge
      subscriptionName: "keda-demo-topic-subscription" # Mandatory
EOF
```

## Test the setup

Now we can send some messages and see if our deployment scales! Use the script `generate-message.sh` to send messages to the queue and monitor the deployment:

```bash
export GCP_PROJECT_ID=$(gcloud config get-value project)
export TOPIC_NAME=keda-demo-topic

chmod +x generate-message.sh
./generate-message.sh
```

In another terminal, watch the deployment scale up as messages arrive:

```bash
kubectl get deployment keda-demo -w
```

Stop the script (Ctrl+C) and, once the subscription's backlog drains, KEDA will automatically scale the number of replicas back down to zero.

## Demo

https://github.com/ChimbuChinnadurai/keda-gke-event-driven-autoscaling-demo/assets/46873109/6c50e633-702c-48c1-a4b0-61ae4e7123da
