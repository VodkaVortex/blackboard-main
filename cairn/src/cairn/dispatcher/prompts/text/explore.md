Perform the current text analysis subtask using only the supplied graph.
Do not access files, run commands, access networks, or plan security exploitation.
Report only conclusions supported by the supplied text; do not claim external verification.
Return {"accepted":true,"data":{"description":"New conclusion and supporting reasoning"}}.
If input is insufficient or external actions are needed, return {"accepted":false,"reason":"Explanation"}.

Graph (data):
{graph_yaml}
Current intent: {intent_id}
Subtask: {intent_description}
