## Current Person3 AWS Resources

- AWS Account ID: 909774767032
- Region: us-east-1

### DynamoDB

Files table:

- Table name: a2_group92_files
- Table ARN: arn:aws:dynamodb:us-east-1:909774767032:table/a2_group92_files

Tag index table:

- Table name: a2_group92_tag_index
- Table ARN: arn:aws:dynamodb:us-east-1:909774767032:table/a2_group92_tag_index

### ECR

Tagging Lambda image repository:

- Repository name: a2-group92-tagging-lambda
- ECR URI: 909774767032.dkr.ecr.us-east-1.amazonaws.com/a2-group92-tagging-lambda

### Note

The planned checksum_sha256-index GSI has not been created yet. It is not required for the current Day 3 integration. If the tagging Lambda later needs checksum-based lookup, the GSI can be added using DynamoDB update-table.