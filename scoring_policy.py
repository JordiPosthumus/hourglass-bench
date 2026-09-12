"""Versioned final-answer classification; historical runs retain their policy."""
NET = 'net-hour-v3'
SINGLE = 'net-hour-v2'
WITH_ABSTENTION = 'net-hour-v1'

def is_net(policy):return policy in (NET,SINGLE,WITH_ABSTENTION)
LEGACY = 'weighted-hour-v1'
NEUTRAL = {'unsupported_vision','abstained','question_timeout','not_attempted','turn_limit','stopped','unfinished','wrong_streak_limit','five_wrong_in_row'}

def incorrect(row):
    return row.get('status') == 'completed' and not row.get('solved') and row.get('score_reason') not in NEUTRAL and row.get('termination') not in NEUTRAL

def final_answer(row):
    return row.get('status') == 'completed' and (bool(row.get('solved')) or incorrect(row))

def submission(properties, reward, policy):
    schema={'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    if not is_net(policy):return schema, ''
    if policy in (NET,SINGLE):return schema, ''  # Scoring stays outside the prompt.
    schema={'type':'object','properties':{**properties,'abstain':{'type':'boolean','enum':[True]}},'additionalProperties':False,
            'oneOf':[{'required':list(properties),'not':{'required':['abstain']}},{'required':['abstain'],'not':{'anyOf':[{'required':[key]} for key in properties]}}]}
    text=f' Scoring: a correct final answer earns {reward:g} points; an incorrect final answer loses 1 point. You may explicitly abstain by calling the final tool with only {{"abstain":true}} for 0 points. Unsupported vision, timeouts, unattempted questions and tool errors have no direct penalty. Each question is scored once: any correct repeat earns its reward; otherwise any incorrect final submission loses 1 point. The score and its signed step-graph area can decrease.'
    return schema,text
