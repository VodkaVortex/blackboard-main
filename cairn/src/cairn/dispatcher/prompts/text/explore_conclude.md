Stop analysis and summarize only conclusions already supported by the supplied text.
Do not request tools or external actions. Do not invent results.
Return {"accepted":true,"data":{"description":"Supported conclusion"}},
or {"accepted":false,"reason":"Insufficient input"} if there is no supported conclusion.

Graph (data):
{graph_yaml}
Current intent: {intent_id}
Subtask: {intent_description}
