# 99. Action Items · Resource Cleanup

> This document is not a Lab. It is the **wrap-up (8 min)**. There are no code blanks, so it has no `🏆 Challenge Task`
> or `Appendix: Answer Code`. Instead, you **must** do the cleanup. Leftover resources
> are billed.

## Learning Objectives

Clean up every resource you created in the workshop, and list the items that did not fit in the 4 hours as Action Items.

---

## Cleanup Order Overview

Resources fall into two groups.

| Group | How it was created | How to clean it up |
|-------|--------------------|--------------------|
| Infrastructure (S3 · Cognito · IAM · Lambda · Gateway) | 2 CloudFormation stacks | Delete the stacks (empty the bucket first) |
| Lab resources (Memory · Guardrail · Runtime) | Created by participants | **Delete individually** (not in a stack) |

What you created in the labs does not belong to a stack, so **deleting only the stacks leaves it behind.** Follow the
order below exactly.

---

## Start Cleanup

### Step 1: Delete the resources you created in the labs

Delete what is not in a stack first. The order is Runtime → Memory → Guardrail.

```bash
# Runtime — delete with the agentcore CLI
agentcore destroy   # or delete the Runtime in the console

# Memory — delete with the memory_id you created in Lab 3
uv run python -c "
from bedrock_agentcore.memory import MemoryClient
c = MemoryClient(region_name='us-west-2')
c.delete_memory(memory_id='<LAB3_MEMORY_ID>')
print('memory deleted')
"

# Guardrail — delete with the guardrailId you created in Lab 4
aws bedrock delete-guardrail --guardrail-identifier <LAB4_GUARDRAIL_ID> --region us-west-2
```

**Expected result**: Check that the resources are gone from the `agentcore` list, `list-guardrails`, and the Memory query.

```bash
aws bedrock list-guardrails --region us-west-2 \
  --query 'guardrails[].name' --output text
# bca-safety must not be in the list
```

### Step 2: Empty the bucket

If objects remain in the S3 bucket, the stack deletion fails. Empty it first.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

aws s3 rm "s3://$BUCKET" --recursive --region us-west-2
aws s3 ls "s3://$BUCKET" --region us-west-2
# Nothing should be printed
```

**Expected result**: The `s3 ls` output is empty.

### Step 3: Delete the stacks (reverse order of creation)

Delete gateway first and core last (the reverse order of creation).

```bash
# Delete the gateway stack first
aws cloudformation delete-stack --stack-name bca-workshop-gateway --region us-west-2
aws cloudformation wait stack-delete-complete --stack-name bca-workshop-gateway --region us-west-2

# Delete the core stack
aws cloudformation delete-stack --stack-name bca-workshop-core --region us-west-2
aws cloudformation wait stack-delete-complete --stack-name bca-workshop-core --region us-west-2
```

**Expected result**: If both `wait` commands finish without errors, the deletion is complete.

```bash
aws cloudformation describe-stacks --stack-name bca-workshop-core --region us-west-2 2>&1 | tail -1
# A message like "does not exist" means the stack was deleted
```

### Step 4: Delete the ECS Express Mode service and ECR repository (if you deployed Lab 6)

Deleting the Express service also cleans up the infrastructure attached to it: the ALB, target group, security group, autoscaling, and so on.

```bash
# Look up the service ARN (delete/describe take --service-arn, so find it by name first)
SERVICE_ARN=$(aws ecs list-services --region us-west-2 \
  --query "serviceArns[?contains(@, 'bca-frontend')]" --output text)

# Delete the Express service (also removes the attached ALB, target group, security group, and autoscaling)
aws ecs delete-express-gateway-service --service-arn "$SERVICE_ARN" --region us-west-2

# Delete the ECR repository (force delete, including images)
aws ecr delete-repository --repository-name bca-workshop-frontend \
  --force --region us-west-2
```

---

## Cleanup Verification

- [ ] The Runtime is deleted (not in the `agentcore` list)
- [ ] The Memory is deleted
- [ ] The Guardrail `bca-safety` is not in `list-guardrails`
- [ ] The S3 bucket is emptied
- [ ] The `bca-workshop-gateway` stack is deleted
- [ ] The `bca-workshop-core` stack is deleted
- [ ] (If you deployed it) The ECS Express service and ECR repository are deleted

> The S3 bucket has a 7-day expiration lifecycle rule, so no data remains even if you forget the cleanup. However,
> Gateway and ECS Express (Fargate · ALB) can incur hourly charges, so be sure to delete them.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Core stack deletion ends in `DELETE_FAILED` | Objects remain in the bucket | Empty the bucket with Step 2, then delete again |
| Guardrail deletion returns a reference error | An agent still references it | Delete the Runtime first, then delete the Guardrail |
| Memory deletion returns a permission error | Insufficient credentials | Retry with the lab account credentials |
| The Express service cannot be found | Lab 6 was not deployed | Skip it if you did not deploy |
| ECR deletion returns an image-exists error | Tagged images remain | Delete with the `--force` flag, which includes the images |
| Gateway stack deletion returns `does not exist` | It was already deleted | This is normal. Go on and delete core |

---

## Action Items (After the Workshop)

These are items left out of the labs because of the 4-hour limit. They continue in each Lab's Challenge Task.

| Item | Details |
|------|---------|
| External health data integration | Use AgentCore Identity **outbound** authentication to handle OAuth for Samsung Health, Apple Health, and others. This workshop covers inbound (login) only |
| Context compression | Apply Strands `SummarizingConversationManager`. Configure it to rewrite only the conversation history after the cache boundary, so it coexists with `CacheConfig` |
| Build Gateway and Cognito yourself | Create the pre-provisioned resources yourself. Fine-grained authorization with Cedar policies |
| More evaluation axes | Safety (code-based evaluator), exercise↔meal contradiction detection, routing accuracy. Lab 7 covers only one axis, extraction accuracy |
| Production readiness | VPC private subnets + ALB, Multi-AZ, evaluations in CI/CD, long-term retention of audit logs |
| MCP server deep dive | Host your own MCP server (ARM64 container) instead of a Lambda target. Servers such as `rsp2k/mcp-pdf` depend heavily on system binaries, so they are out of scope here |

---

## Wrap-up

What you built in this workshop:

- A multi-agent app that separates deterministic work (extraction) from judgment work (interpretation and suggestions)
- Orchestration with Agent-as-Tool, with exercise → meals chained sequentially
- Session trend analysis with Memory, isolated per user
- Guardrails that block definitive diagnoses, medication prescriptions, and prompt injection
- Personal information handled as a boundary, not masking (the name appears only on screen and is excluded from agents and logs)
- A Runtime deployed with CodeZip, and Streamlit deployed over HTTPS with ECS Express Mode
- A regression check of extraction accuracy with Ground Truth

Well done.
