Execute the current general development or assistance subtask, using native tools
when useful. Read relevant files, make requested changes, and verify the result.
Report observed results and remaining issues, not just a plan or an unsupported claim.
Return {"accepted":true,"data":{"description":"New results, paths, and verification"}}.
If blocked on user input or unable to proceed, return {"accepted":false,"reason":"Explain the blocker"}.
Your final response must be only one JSON object after tool use.

Graph (context):
{graph_yaml}
Current intent: {intent_id}
Subtask: {intent_description}
