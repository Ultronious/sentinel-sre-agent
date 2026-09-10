````markdown
# AWS Field Manual

> Hands-on AWS lessons, failures, architecture decisions, debugging patterns,
> mental models, and SAA concepts learned by building real systems.

This document is intentionally based on practical experience.

The goal is not to memorize AWS documentation.

The goal is:

**Build → Break → Investigate → Understand → Fix → Document → Generalize**

Projects contributing to this field manual:

- Sentinel — Agentic SRE / Cloud Operations Agent
- S3 → CloudFront → API Gateway → Lambda serverless project
- Self-managed GenAI on AWS → EKS → vLLM
- AWS Solutions Architect Associate (SAA) preparation


---

# 1. Identity, Authentication & Authorization

## 1.1 Root Account vs. Human Developer Access

### What happened

Initially, the AWS CLI was authenticated as the AWS account root identity.

We discovered this with:

```powershell
aws sts get-caller-identity
````

The returned ARN identified the root principal.

### Why this matters

The AWS CLI does not inherently know that the person using it is a developer.

AWS API calls are made using credentials associated with an AWS principal.

Therefore, before troubleshooting permissions, determine:

1. Which AWS account?
2. Which region?
3. Which principal?
4. Which role?
5. Which permissions?
6. Which resource?

### SAA lesson

Never assume the identity behind an AWS CLI command.

**Verify the principal first.**

---

## 1.2 AWS IAM Identity Center

We configured AWS IAM Identity Center for human AWS access.

Our eventual authentication flow is:

```text
Human
  |
  v
IAM Identity Center
  |
  v
Identity Center User
  |
  v
Permission Set
  |
  v
AWS Account
  |
  v
AWSReservedSSO IAM Role
  |
  v
Temporary STS Credentials
  |
  v
AWS APIs
```

### Important distinction

IAM Identity Center users and IAM users are different identity systems.

We encountered two identities with the display name:

```text
Arpan
```

but they represented different principals.

### Lesson

Do not identify AWS principals by display name alone.

Use identity information such as:

* ARN
* AWS account ID
* STS identity
* role/session information

---

# 2. IAM Identity Center Instance Types

## 2.1 Account Instance vs Organization Instance

### What happened

We initially created an IAM Identity Center account instance.

This was not the model required for the AWS account-access workflow we wanted.

We deleted the account instance and created an organization instance instead.

### Lesson

AWS services and features can have different scopes and deployment models.

Before creating a resource, ask:

* What scope does it operate at?
* Is it account-level or organization-level?
* What capabilities does this deployment model provide?
* What resources can it manage?

### General SAA principle

> Understand the scope of a service before choosing its configuration.

This pattern will matter later with:

* AWS Organizations
* IAM Identity Center
* VPCs
* regional services
* global services
* EKS
* CloudFront

---

# 3. Permission Sets

## 3.1 SentinelPowerUser

We created a permission set:

```text
SentinelPowerUser
```

using:

```text
PowerUserAccess
```

for development.

The permission set is assigned to the Identity Center user and the AWS account.

The resulting conceptual flow is:

```text
Identity Center User
        |
        v
SentinelPowerUser
        |
        v
AWS Account
        |
        v
AWSReservedSSO_SentinelPowerUser_...
        |
        v
Temporary credentials
```

### Why Permission Sets Matter

A permission set defines the permissions a user or group receives when accessing an AWS account through IAM Identity Center.

### Production lesson

For real production systems, prefer least privilege.

For this disposable development environment, broad developer permissions are being used to reduce unnecessary IAM friction.

The Sentinel agent itself should not automatically receive:

```text
AdministratorAccess
```

The human developer's permissions and the workload's permissions should be treated as separate security boundaries.

---

# 4. AWS CLI Profiles

## 4.1 Sentinel Profile

We created a dedicated AWS CLI profile:

```text
sentinel
```

Configure:

```powershell
aws configure sso --profile sentinel
```

Authenticate:

```powershell
aws sso login --profile sentinel
```

Verify:

```powershell
aws sts get-caller-identity --profile sentinel
```

The successful identity looked like:

```text
arn:aws:sts::<ACCOUNT_ID>:assumed-role/AWSReservedSSO_SentinelPowerUser_.../Arpan
```

### Why this matters

CLI profiles allow different environments to have separate:

* credentials
* regions
* configuration
* authentication mechanisms

Potential future profiles:

```text
sentinel
serverless-lab
genai-eks
```

### SAA / operational lesson

Separate environments and identities rather than relying on whichever credentials happen to be active.

---

# 5. STS Identity Verification

## 5.1 The Identity Verification Rule

Before performing important or destructive AWS operations:

```powershell
aws sts get-caller-identity --profile sentinel
```

Verify:

```text
AWS Account
Principal
Role
Session
```

### Mental model

```text
WHO AM I?
    |
    v
WHICH ACCOUNT?
    |
    v
WHICH REGION?
    |
    v
WHAT RESOURCE?
    |
    v
WHAT PERMISSIONS?
    |
    v
WHAT NETWORK PATH?
    |
    v
WHAT CHANGED?
```

### Why STS is useful

Instead of guessing which credentials are active, ask AWS directly.

The command:

```powershell
aws sts get-caller-identity
```

is one of the most useful first checks when troubleshooting AWS CLI authentication.

---

# 6. AWS CLI Debugging

## 6.1 Basic Identity Check

```powershell
aws sts get-caller-identity --profile sentinel
```

---

## 6.2 Check Region

```powershell
aws configure get region --profile sentinel
```

Current development region:

```text
us-east-1
```

---

## 6.3 Check Availability Zones

```powershell
aws ec2 describe-availability-zones `
  --region us-east-1 `
  --profile sentinel
```

### Lesson

AWS resources are not all global.

Always understand whether a resource is:

* Global
* Regional
* Availability-Zone specific

---

# 7. PowerShell Environment Demon

## 7.1 `curl` Is Not Necessarily curl

### What happened

We attempted:

```powershell
curl http://127.0.0.1:8000/health
```

PowerShell interpreted `curl` as:

```text
Invoke-WebRequest
```

rather than the native curl executable.

PowerShell displayed a script-execution warning.

### Resolution

Use the native executable explicitly:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Alternatively:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
```

### Useful diagnostic

```powershell
Get-Command curl
```

This shows what PowerShell resolves `curl` to.

### Lesson

When a command behaves differently from a Linux/macOS tutorial, determine whether the shell is providing an alias or a different implementation.

This is not an AWS problem, but environment-specific behavior can become a major source of debugging noise during cloud development.

---

# 8. Docker Fundamentals

## 8.1 Docker CLI vs Docker Engine

### What happened

Initially:

```powershell
docker --version
```

worked.

However:

```powershell
docker info
```

failed.

### Symptom

The Docker CLI was installed, but it could not communicate with the Docker Engine.

The active Docker context was:

```text
desktop-linux
```

Docker Desktop was not running.

### Investigation

```powershell
docker context ls
```

```powershell
docker desktop status
```

```powershell
docker info
```

### Resolution

Docker Desktop was started:

```powershell
docker desktop start
```

After startup,:

```powershell
docker info
```

successfully returned both Client and Server information.

### Mental model

```text
Docker CLI
    |
    | Docker API
    v
Docker Engine
    |
    +-- Images
    +-- Containers
    +-- Networks
    +-- Volumes
```

The CLI is the client.

The Engine performs the actual container operations.

Therefore:

```text
docker --version
    |
    +--> checks CLI installation

docker info
    |
    +--> checks communication with Docker Engine
```

### Lesson

A working Docker CLI does not imply that the Docker Engine is running.

When Docker commands fail, determine whether the problem is:

1. Docker CLI
2. Docker context
3. Docker Desktop
4. Docker Engine

---

# 9. Docker Desktop + WSL2

Our development environment is:

```text
Windows
   |
   v
PowerShell
   |
   v
Docker CLI
   |
   v
Docker Desktop
   |
   v
WSL2
   |
   v
Linux Docker Engine
```

The Docker Engine reports:

```text
OSType: linux
Architecture: x86_64
```

and uses the WSL2-based Linux environment provided by Docker Desktop.

### Lesson

Even though the development machine is Windows, our Docker workload is using a Linux container environment.

This becomes useful later because the container we build locally can become an artifact deployed to AWS services such as ECS/Fargate.

---

# 10. Local Application Architecture

Before deploying anything to AWS, we built a small local FastAPI application.

Current structure:

```text
sentinel-sre-agent/
│
└── app/
    ├── app.py
    ├── requirements.txt
    └── Dockerfile
```

The application uses:

```text
FastAPI
Uvicorn
```

---

## 10.1 FastAPI

The application creates a FastAPI instance:

```python
app = FastAPI(title="Sentinel Demo Service")
```

Routes are defined using HTTP methods and paths.

For example:

```python
@app.get("/health")
def health():
    return {"status": "healthy"}
```

This means:

```text
HTTP GET /health
        |
        v
health()
        |
        v
JSON response
```

### Mental model

```text
HTTP Request
     |
     v
Uvicorn
     |
     v
FastAPI
     |
     v
Route
     |
     v
Python Function
     |
     v
HTTP Response
```

---

# 11. Uvicorn

Uvicorn is the server used to run the FastAPI application.

We started it with:

```powershell
uvicorn app.app:app --reload
```

The syntax:

```text
app.app:app
```

means approximately:

```text
Python module : application object
```

Our structure is:

```text
app/
└── app.py
```

and inside `app.py`:

```python
app = FastAPI(...)
```

Therefore Uvicorn loads the FastAPI application object from the Python module.

---

# 12. Localhost and Ports

The application runs locally on:

```text
127.0.0.1:8000
```

`127.0.0.1` refers to the local machine.

Port `8000` identifies the network endpoint where our application is listening.

Conceptually:

```text
Computer
│
├── other services
│
└── :8000
      |
      v
   FastAPI
```

When we execute:

```powershell
curl.exe http://127.0.0.1:8000/health
```

the request travels conceptually through:

```text
PowerShell
    |
    v
HTTP request
    |
    v
127.0.0.1:8000
    |
    v
Uvicorn
    |
    v
FastAPI router
    |
    v
health()
    |
    v
HTTP response
```

### Important distinction

`127.0.0.1` is local to the environment where the request is being made.

This becomes particularly important once containers are introduced because:

```text
localhost inside a container
```

does not necessarily refer to:

```text
localhost on the host machine
```

This will be explored during container networking.

---

# 13. Sentinel Demo Application

The application currently exposes:

```text
GET /health
GET /api
GET /metrics-demo
GET /admin/inject-latency
GET /admin/inject-errors
```

---

## 13.1 `/health`

Purpose:

Provide a simple health endpoint.

Example:

```text
GET /health
        |
        v
{"status": "healthy"}
```

Later this can be used as part of an AWS load balancer health-check design.

---

## 13.2 `/api`

Represents a normal application request.

Purpose:

Provide a basic workload endpoint that can be observed while the application is running.

---

## 13.3 `/metrics-demo`

Provides simple request-related information such as:

* request ID
* timestamp

This is currently only a demonstration endpoint.

It is not yet CloudWatch metrics.

Actual observability will be introduced later.

---

# 14. Controlled Failure Injection

Sentinel is an SRE agent.

Therefore, we need a system capable of producing controlled operational incidents.

Instead of waiting for random failures, the demo application contains deliberate failure mechanisms.

---

## 14.1 Latency Injection

Endpoint:

```text
/admin/inject-latency
```

Example:

```text
/admin/inject-latency?seconds=5
```

The application deliberately waits before responding.

Conceptually:

```text
Request
   |
   v
Application
   |
   +---- deliberate delay
   |
   v
Slow response
```

This allows us to eventually demonstrate:

```text
Latency increases
       |
       v
CloudWatch observes signal
       |
       v
Alarm
       |
       v
Sentinel investigates
```

---

## 14.2 Error Injection

Endpoint:

```text
/admin/inject-errors
```

The application deliberately raises an exception.

Conceptually:

```text
HTTP Request
     |
     v
Application
     |
     v
RuntimeError
     |
     v
HTTP 500
```

Later the error should become observable through AWS logging and monitoring systems.

---

# 15. Why Build the Failure Before the Agent?

Sentinel's purpose is to investigate operational incidents.

Therefore, the first component we build is not the agent.

We first build and understand the system the agent will operate on.

### Principle

> Understand the system before automating its operations.

The agent should eventually investigate evidence such as:

* latency
* errors
* application logs
* infrastructure state
* ECS task state
* deployments
* recent changes
* CloudTrail activity

The agent should not simply implement:

```text
Alarm X → Remediation Y
```

That would be deterministic automation.

The intended workflow is:

```text
Signal
  |
  v
Investigation
  |
  v
Evidence gathering
  |
  v
Hypothesis
  |
  v
Validation
  |
  v
Decision
  |
  v
Human approval when required
  |
  v
Remediation
  |
  v
Verification
```

---

# 16. Sentinel Target Architecture

The target AWS workload is an ECS/Fargate application.

Initial architecture:

```text
                    Internet
                       |
                       v
              Application Load
                 Balancer
                       |
                       v
                 ECS Service
                       |
                       v
                Fargate Task
                       |
                       v
                 FastAPI App
```

Supporting services:

```text
ECR
 |
 v
Container Image
 |
 v
ECS/Fargate
 |
 v
CloudWatch
 ├── Logs
 ├── Metrics
 └── Alarms
```

Network design:

```text
VPC
│
├── Public Subnet AZ-a
│
├── Public Subnet AZ-b
│
├── Internet Gateway
│
├── Application Load Balancer
│
└── ECS/Fargate Task
```

Initial design intentionally avoids a NAT Gateway to reduce unnecessary development cost.

The Fargate task can use a public subnet and public IP for the initial disposable development environment.

This architecture will be refined as we build and observe the actual behavior.

---

# 17. Containerization Mental Model

The planned container flow is:

```text
Application
    |
    v
Dockerfile
    |
    | docker build
    v
Docker Image
    |
    | docker run
    v
Container
    |
    | docker push
    v
ECR
    |
    v
ECS/Fargate
```

Important distinction:

```text
Image
=
packaged artifact / template

Container
=
running instance of an image
```

A Python virtual environment is not equivalent to a container.

A Python virtual environment primarily isolates Python packages.

A container provides a broader packaged runtime environment around an application.

---

# 18. Current Dockerfile Checkpoint

The Dockerfile currently begins with:

```dockerfile
FROM python:3.12-slim
```

The purpose and implications of `FROM` will be studied before adding additional Dockerfile instructions.

Planned concepts:

```text
FROM
WORKDIR
COPY
RUN
EXPOSE
CMD
```

The goal is to understand every instruction rather than treat the Dockerfile as a template to copy.

---

# 19. ECR

To be expanded while containerizing and deploying Sentinel.

Topics:

* ECR repositories
* Container images
* Image tags
* Authentication
* Push
* Pull
* Image lifecycle
* Image scanning
* IAM permissions
* Registry vs repository

---

# 20. ECS / Fargate

To be expanded during deployment.

Topics:

* ECS cluster
* Task definitions
* Tasks
* Services
* Fargate
* `awsvpc`
* Task role
* Execution role
* CPU
* Memory
* Desired count
* Deployment
* Health checks
* Networking

---

# 21. Application Load Balancer

To be expanded during deployment.

Topics:

* ALB
* Listener
* Target groups
* Health checks
* Security groups
* Routing
* ECS integration

---

# 22. CloudWatch & Observability

To be expanded during AWS deployment.

Topics:

* CloudWatch Logs
* Log groups
* Metrics
* Alarms
* Dashboards
* Logs Insights
* Metric filters
* Application signals
* ECS monitoring

---

# 23. Sentinel SRE Agent

The intended agent architecture is:

```text
AWS Signal
     |
     v
Strands Agent
     |
     +--> Metrics
     |
     +--> Logs
     |
     +--> AWS Resource State
     |
     +--> Recent Changes
     |
     +--> CloudTrail
     |
     v
Evidence Correlation
     |
     v
Root Cause Hypothesis
     |
     v
Validation
     |
     v
Human Approval
     |
     v
Guarded Remediation
     |
     v
Verification
```

Potential tools:

```text
get_alarm_state()
get_metrics()
query_logs()
inspect_resource()
get_recent_changes()
query_cloudtrail()
```

Potential guarded actions:

```text
request_remediation()
execute_remediation()
verify_remediation()
```

### Autonomy boundary

Read operations:

```text
Autonomous
```

Diagnosis:

```text
Autonomous
```

Recommendations:

```text
Autonomous
```

Mutating or destructive actions:

```text
Human approval required
```

Verification:

```text
Autonomous
```

### Core philosophy

> Sentinel protects engineers' attention; it does not replace engineering judgment.

---

# 24. Serverless Project Cross-Reference

Planned architecture:

```text
User
 |
 v
CloudFront
 |
 v
API Gateway
 |
 v
Lambda
 |
 v
AWS Services
```

Topics to connect to SAA study:

* S3
* CloudFront
* API Gateway
* Lambda
* IAM
* CORS
* CloudWatch
* caching
* origins
* permissions
* error handling
* serverless architecture
* availability
* cost

---

# 25. Self-Managed GenAI on AWS

Planned architecture:

```text
User
 |
 v
Application
 |
 v
Load Balancer
 |
 v
EKS
 |
 v
Inference Pods
 |
 v
vLLM
 |
 v
GPU
 |
 v
Foundation Model
```

Topics:

* EKS
* Kubernetes
* EC2
* Node groups
* GPU instances
* ECR
* vLLM
* model serving
* persistent storage
* networking
* IAM
* workload identity
* autoscaling
* observability
* cost management

---

# 26. IAM & Workload Identity

Topics to study through hands-on implementation:

* IAM users
* IAM groups
* IAM roles
* Permission Sets
* IAM Identity Center
* STS
* Temporary credentials
* Trust policies
* Permissions policies
* Least privilege
* ECS task roles
* ECS execution roles
* Lambda execution roles
* EKS workload identity

### Important mental model

Human identity:

```text
Human
  |
  v
Identity Center
  |
  v
Temporary AWS role
```

Workload identity:

```text
Application / Task / Pod
  |
  v
Workload IAM role
  |
  v
AWS API
```

Do not put long-lived human access keys inside workloads.

---

# 27. AWS Networking

Topics to study through actual deployments:

* VPC
* CIDR
* Subnets
* Public vs private subnets
* Route tables
* Internet Gateway
* NAT Gateway
* Security Groups
* Network ACLs
* DNS
* Availability Zones
* Load Balancers
* VPC endpoints
* routing
* ingress
* egress

### Mental model

When something cannot communicate:

```text
Source
  |
  v
DNS?
  |
  v
Route?
  |
  v
Security Group?
  |
  v
Network ACL?
  |
  v
Destination?
```

Don't immediately change random settings.

Trace the path.

---

# 28. AWS Cost & FinOps

Topics:

* Cost Explorer
* Budgets
* Billing
* Free Tier
* Fargate pricing
* NAT Gateway costs
* Load Balancer costs
* CloudWatch costs
* EKS costs
* GPU costs
* Data transfer
* cleanup

### Resource creation rule

Before creating an AWS resource:

```text
What does it cost?
       |
       v
How long will it exist?
       |
       v
What dependencies does it create?
       |
       v
How do I destroy it?
```

### Development principle

Prefer the smallest architecture that demonstrates the required concept.

Avoid unnecessary infrastructure.

---

# 29. Failure & Debugging Journal

Every meaningful failure should be documented.

Use this template:

## Incident: <short name>

### Symptom

What happened?

### My assumption

What did I initially believe?

### Actual cause

What was really happening?

### Investigation

What commands, logs, console information, or tests helped?

### Fix

What changed?

### AWS concept

What AWS concept does this represent?

### SAA lesson

What should I remember for the exam?

### Real-world lesson

What should I do differently in production?

### Reusable debugging command

```powershell
<command>
```

---

# 30. Things I Got Wrong

This is intentionally one of the most important sections.

Current examples:

* Used root credentials from the CLI
* Confused IAM users with IAM Identity Center users
* Created the wrong IAM Identity Center instance type
* Assumed console login and CLI identity were the same thing
* Did not verify the active AWS principal first
* Discovered that PowerShell `curl` can resolve to `Invoke-WebRequest`
* Discovered that Docker CLI can work while Docker Engine is stopped

Add future mistakes here.

### Principle

> A mistake that has been investigated and understood becomes reusable knowledge.

---

# 31. AWS Mental Models

Short rules intended to become instinctive.

## Identity

```text
Who is making the API call?
```

## Account

```text
Which AWS account am I operating in?
```

## Region

```text
Which region is this resource in?
```

## Networking

```text
Can packets actually get there?
```

## IAM

```text
Is this principal trusted AND authorized?
```

## Availability

```text
What happens if this AZ/resource fails?
```

## Scalability

```text
What happens when load increases?
```

## Observability

```text
How will I know it failed?
```

## Security

```text
What is the smallest permission this component needs?
```

## Cost

```text
What am I paying for while this exists?
```

## Cleanup

```text
How do I destroy it safely?
```

---

# 32. SAA Concepts Learned Through Hands-On Work

For every major AWS concept, capture:

```text
Concept
   |
   +--> What AWS provides
   |
   +--> Why it exists
   |
   +--> When to use it
   |
   +--> When NOT to use it
   |
   +--> Architecture implications
   |
   +--> Cost implications
   |
   +--> Security implications
   |
   +--> Failure modes
   |
   +--> SAA exam traps
```

The objective is to turn practical experience into exam-ready architectural knowledge.

---

# 33. Project Cross-Reference

## Sentinel SRE Agent

```text
ECS
Fargate
ALB
VPC
ECR
CloudWatch
IAM
STS
Strands
AgentCore
Docker
```

## Serverless Project

```text
S3
CloudFront
API Gateway
Lambda
IAM
CloudWatch
CORS
Caching
```

## Self-Managed GenAI

```text
EKS
EC2
GPU
ECR
vLLM
Kubernetes
IAM
VPC
Load Balancer
CloudWatch
Autoscaling
```

### Why this matters

The same AWS concept often appears in different architectures.

For example:

```text
IAM
 |
 +--> Lambda
 |
 +--> ECS
 |
 +--> EKS
 |
 +--> CLI
 |
 +--> Sentinel
```

Learning the underlying concept once and seeing it applied repeatedly is more useful than memorizing isolated service tutorials.

---

# 34. Final SAA Revision

Before the SAA exam, convert this field manual into:

* Architecture patterns
* Service comparisons
* Decision trees
* Cost traps
* Security traps
* Networking traps
* High availability patterns
* Disaster recovery patterns
* IAM patterns
* Serverless patterns
* Container patterns
* Monitoring patterns
* Exam questions based on actual mistakes

The objective is to transform:

```text
Hands-on experience
        |
        v
AWS mental model
        |
        v
Architecture reasoning
        |
        v
SAA exam knowledge
```

---

# 35. Core Learning Philosophy

This field manual is not intended to become a collection of copied AWS documentation.

The preferred learning cycle is:

```text
Learn enough
    |
    v
Build
    |
    v
Observe
    |
    v
Break
    |
    v
Investigate
    |
    v
Understand
    |
    v
Fix
    |
    v
Document
    |
    v
Generalize
```

The goal is not merely to say:

> "I used AWS service X."

The goal is to be able to explain:

> **Why service X was selected, what problem it solves, what alternatives exist, what tradeoffs it introduces, how it fails, how it is secured, how it costs money, and how it fits into the architecture.**

That is the difference between following an AWS tutorial and actually learning AWS.

---

# Current Checkpoint

## Completed

* AWS IAM Identity Center organization instance
* SentinelPowerUser permission set
* AWS CLI SSO profile
* Temporary STS credentials
* Identity verification
* Sentinel project skeleton
* Python virtual environment
* FastAPI application
* Uvicorn
* Local HTTP testing
* Controlled latency injection
* Controlled error injection
* Docker Desktop
* Docker Linux Engine
* Docker context verification
* Initial Dockerfile
* `FROM python:3.12-slim`

## Next

```text
Dockerfile
    |
    v
Docker Image
    |
    v
Container
    |
    v
Container Networking
    |
    v
ECR
    |
    v
VPC
    |
    v
ALB
    |
    v
ECS/Fargate
    |
    v
CloudWatch
    |
    v
Controlled AWS Incident
    |
    v
Strands Agent
```

---

# Final Principle

> **I don't want to merely use AWS. I want to understand why AWS works.**

> **Build it. Break it. Fix it. Understand it.**




