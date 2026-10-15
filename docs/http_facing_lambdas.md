# HTTP-facing Lambda Functions

These Lambda functions are designed to be invoked by API Gateway. They are Python zip-based Lambdas and do not use the model container image.

## Shared Environment Variables

| Variable | Value |
|---|---|
| `FILES_TABLE` | `a2_group92_files` |
| `TAG_INDEX_TABLE` | `a2_group92_tag_index` |
| `ACTION` | Different for each Lambda |

## Lambda Function Mapping

| API purpose | Lambda function | ACTION |
|---|---|---|
| Query files by tags with minimum counts | `a2-group92-query-tags` | `query_tags` |
| Query files by one species/tag | `a2-group92-query-species` | `query_species` |
| Query full image URL by thumbnail URL | `a2-group92-query-thumbnail` | `query_thumbnail` |
| Query files by detected tags from a query file | `a2-group92-query-file` | `query_file` |
| Bulk add/remove manual tags | `a2-group92-tags-edit` | `tags_edit` |
| Delete files and related metadata | `a2-group92-delete-files` | `delete_files` |

## Example Request Bodies

### Query by tags

```json
{
  "tags": {
    "koala": 2,
    "wombat": 1
  }
}