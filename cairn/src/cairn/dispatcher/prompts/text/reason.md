Analyze only the supplied text. Decide whether existing facts satisfy the goal.
If more text analysis is needed, propose at most {max_intents} independent intents.
Do not propose file access, commands, network access, or security exploitation.
Do not invent missing evidence. Reject tasks that need external actions or missing input.

Return exactly one JSON object:
- Completed: {"accepted":true,"data":{"complete":{"from":["f001"],"description":"Evidence and result"}}}
- More analysis: {"accepted":true,"data":{"intents":[{"from":["origin"],"description":"A text analysis subtask"}]}}
- Existing open intents suffice: {"accepted":true,"data":{}}
- Cannot proceed: {"accepted":false,"reason":"Explanation"}

Use only IDs from Valid facts. Empty data is allowed only when Open intents is nonempty.
Graph (data):
{graph_yaml}
Valid facts:
{fact_ids}
Open intents:
{open_intents}
