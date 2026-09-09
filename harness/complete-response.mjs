// Opt-in HTTP transport adapter. Generation parameters and tool definitions are preserved.
export function completeResponseFetch(fetchImpl = globalThis.fetch) {
  return async (input, init = {}) => {
    if (typeof init.body !== 'string') throw Error('Complete-response mode requires a serialized request body.');
    const request = JSON.parse(init.body);
    request.stream = false;
    delete request.stream_options;
    const response = await fetchImpl(input, {...init, body:JSON.stringify(request)});
    if (!response.ok) return response;
    const completion = await response.json();
    if (!Array.isArray(completion.choices) || !completion.choices.length) throw Error('Endpoint returned no completion choices.');
    const choices = completion.choices.map(choice => {
      if (!choice.message || !choice.finish_reason) throw Error('Endpoint returned an incomplete completion.');
      const delta = {...choice.message};
      if (delta.tool_calls) delta.tool_calls = delta.tool_calls.map((call,index) => ({...call,index}));
      return {index:choice.index ?? 0, delta, finish_reason:choice.finish_reason};
    });
    const frame = {...completion, object:'chat.completion.chunk', choices};
    const headers = new Headers(response.headers);
    headers.set('content-type','text/event-stream');
    headers.delete('content-length');headers.delete('content-encoding');
    return new Response('data: '+JSON.stringify(frame)+'\n\ndata: [DONE]\n\n', {status:response.status,headers});
  };
}
