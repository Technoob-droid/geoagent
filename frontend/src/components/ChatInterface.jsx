import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Send, Terminal, Sparkles, Loader2 } from 'lucide-react';

export default function ChatInterface({ onNewLayerDiscovered, onLayerDeleted, viewportBbox }) {
  const [prompt, setPrompt] = useState('');
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hello! I am GeoAgent. I can run metric spatial buffers, detect intersections, and execute DuckDB Spatial queries over loaded geodata. What analysis would you like to run?'
    }
  ]);
  const [toolLogs, setToolLogs] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, toolLogs]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!prompt.trim() || isProcessing) return;

    const userText = prompt.trim();
    setPrompt('');
    setMessages((prev) => [...prev, { role: 'user', content: userText }]);
    setIsProcessing(true);
    setToolLogs([]);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: userText,
          viewport_bbox: viewportBbox
        })
      });

      if (!response.body) throw new Error('Readable stream not supported.');

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let assistantMsg = '';
      let buffer = '';

      setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const dataStr = line.replace('data: ', '').trim();
          if (dataStr === '[DONE]') continue;

          try {
            const event = JSON.parse(dataStr);

            if (event.type === 'token') {
              assistantMsg += event.content;
              setMessages((prev) => {
                const copy = [...prev];
                copy[copy.length - 1] = { role: 'assistant', content: assistantMsg };
                return copy;
              });
            } else if (event.type === 'tool_start') {
              setToolLogs((prev) => [
                ...prev,
                { type: 'start', tool: event.tool, input: event.input }
              ]);
            } else if (event.type === 'tool_end') {
              setToolLogs((prev) => [
                ...prev,
                { type: 'end', tool: event.tool, output: event.output }
              ]);
            } else if (event.type === 'new_layer') {
              onNewLayerDiscovered(event.layer);
            } else if (event.type === 'delete_layer') {
              if (onLayerDeleted) onLayerDeleted(event.layer_id);
            }
          } catch (pErr) {
            console.warn('Non-JSON SSE event payload:', dataStr);
          }
        }
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Execution Error: ${err.message}` }
      ]);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border-r border-slate-800 text-slate-200">
      {/* Header */}
      <div className="p-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Sparkles className="w-5 h-5 text-indigo-400" />
          <h1 className="font-semibold text-sm tracking-wide uppercase text-slate-100">
            GeoAgent Console
          </h1>
        </div>
        <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800">
          Spatial Engine Active
        </span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((m, idx) => (
          <div
            key={idx}
            className={`flex flex-col ${
              m.role === 'user' ? 'items-end' : 'items-start'
            }`}
          >
            <div
              className={`max-w-[85%] rounded-lg p-3 text-sm leading-relaxed ${
                m.role === 'user'
                  ? 'bg-indigo-600 text-white shadow-md'
                  : 'bg-slate-800 text-slate-200 border border-slate-700 overflow-x-auto'
              }`}
            >
              {m.role === 'assistant' ? (
                m.content ? (
                  <div className="markdown-body text-xs sm:text-sm">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        p: ({ node, ...props }) => <p className="mb-2 last:mb-0 leading-relaxed" {...props} />,
                        strong: ({ node, ...props }) => <strong className="font-semibold text-sky-300" {...props} />,
                        code: ({ node, className, children, ...props }) => {
                          const isBlock = /language-/.test(className || '') || String(children).includes('\n');
                          return isBlock ? (
                            <pre className="bg-slate-950 p-2.5 rounded my-2 overflow-x-auto border border-slate-800">
                              <code className="font-mono text-xs text-slate-300" {...props}>
                                {children}
                              </code>
                            </pre>
                          ) : (
                            <code className="bg-slate-900/90 text-indigo-300 px-1.5 py-0.5 rounded font-mono text-xs border border-slate-700 inline-block align-baseline" {...props}>
                              {children}
                            </code>
                          );
                        },
                        table: ({ node, ...props }) => (
                          <div className="overflow-x-auto my-3 rounded border border-slate-700 shadow-sm">
                            <table className="min-w-full border-collapse text-left text-xs" {...props} />
                          </div>
                        ),
                        thead: ({ node, ...props }) => <thead className="bg-slate-900/90 border-b border-slate-700" {...props} />,
                        tbody: ({ node, ...props }) => <tbody className="divide-y divide-slate-700/60 bg-slate-900/40" {...props} />,
                        tr: ({ node, ...props }) => <tr className="hover:bg-slate-700/30 transition-colors" {...props} />,
                        th: ({ node, ...props }) => (
                          <th className="px-3 py-2 font-semibold text-slate-300 uppercase tracking-wider text-[11px]" {...props} />
                        ),
                        td: ({ node, ...props }) => (
                          <td className="px-3 py-2 text-slate-300 font-mono" {...props} />
                        ),
                        ul: ({ node, ...props }) => <ul className="list-disc pl-4 space-y-1 my-2" {...props} />,
                        ol: ({ node, ...props }) => <ol className="list-decimal pl-4 space-y-1 my-2" {...props} />,
                        li: ({ node, ...props }) => <li className="text-slate-300" {...props} />
                      }}
                    >
                      {m.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  isProcessing && idx === messages.length - 1 ? (
                    <div className="flex items-center space-x-2 text-slate-400">
                      <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
                      <span>Analyzing spatial topology...</span>
                    </div>
                  ) : null
                )
              ) : (
                <span>{m.content}</span>
              )}
            </div>
          </div>
        ))}

        {/* Live Tool Traces */}
        {toolLogs.length > 0 && (
          <div className="bg-slate-950 border border-slate-800 rounded-md p-3 text-xs font-mono space-y-2">
            <div className="flex items-center space-x-1 text-slate-400 pb-1 border-b border-slate-800">
              <Terminal className="w-3.5 h-3.5 text-amber-400" />
              <span>Spatial Execution Trace</span>
            </div>
            {toolLogs.map((log, i) => (
              <div key={i} className="text-slate-300">
                {log.type === 'start' ? (
                  <span className="text-amber-400 font-medium">
                    ▶ Invoking tool: {log.tool}
                  </span>
                ) : (
                  <span className="text-emerald-400">
                    ✓ Completed: {log.tool}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-slate-800">
        <div className="relative">
          <input
            type="text"
            className="w-full bg-slate-950 border border-slate-800 rounded-md pl-3 pr-10 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition"
            placeholder="e.g. Create a 1km buffer around hospitals and find flood overlap..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={isProcessing}
          />
          <button
            type="submit"
            disabled={isProcessing || !prompt.trim()}
            className="absolute right-1.5 top-1.5 bottom-1.5 px-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded transition flex items-center justify-center"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </form>
    </div>
  );
}