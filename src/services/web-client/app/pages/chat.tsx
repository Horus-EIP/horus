import React, { useState, useEffect, useRef } from 'react';
import { Send, Bot, User } from 'lucide-react';

interface Message {
    id: string;
    text: string;
    sender: 'user' | 'agent';
    timestamp: Date;
}

const Chat = () => {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState<string>('');
    const [isLoading, setIsLoading] = useState<boolean>(false);
    const [conversationId, setConversationId] = useState<string>('');
    const ws = useRef<WebSocket | null>(null);

    // Initialisation de la conversation et connexion WebSocket
    useEffect(() => {
        const createConversation = async () => {
            try {
                const response = await fetch('http://localhost:8000/conversations/create-conversation/', {
                    method: 'POST'
                });

                const data = await response.json();
                setConversationId(data.conversation_id);

                // Connexion WebSocket
                ws.current = new WebSocket(`ws://localhost:8000/chat/${data.conversation_id}/`);

                // Gestion des messages entrants
                ws.current.onmessage = (event) => {
                    const message = JSON.parse(event.data);
                    if (message.type === 'agent') {
                        const agentMessage: Message = {
                            id: Date.now().toString(),
                            text: message.content,
                            sender: 'agent',
                            timestamp: new Date(message.timestamp)
                        };
                        setMessages(prev => [...prev, agentMessage]);
                        setIsLoading(false);
                    }
                };

                // Gestion des erreurs
                ws.current.onerror = (error) => {
                    console.error('WebSocket error:', error);
                    setIsLoading(false);
                };

                ws.current.onclose = () => {
                    console.log('WebSocket disconnected');
                    setIsLoading(false);
                };

            } catch (error) {
                console.error('Error creating conversation:', error);
            }
        };

        createConversation();

        return () => {
            if (ws.current) {
                ws.current.close();
            }
        };
    }, []);

    // Récupération de l'historique
    useEffect(() => {
        const fetchHistory = async () => {
            if (!conversationId) return;

            try {
                const response = await fetch(
                    `http://localhost:8000/conversations/get_history/${conversationId}`
                );
                const data: { role: 'user' | 'assistant'; message: string }[] = await response.json();

                // Backend returns a list of { role: 'user'|'assistant', message: string }
                const historyMessages: Message[] = data.map((msg, idx: number) => ({
                    id: `${Date.now()}-${idx}`,
                    text: msg.message,
                    sender: msg.role === 'user' ? ('user' as const) : ('agent' as const),
                    timestamp: new Date(),
                }));

                setMessages(historyMessages);
            } catch (error) {
                console.error('Error fetching history:', error);
            }
        };

        fetchHistory();
    }, [conversationId]);

    // Soumission des messages
    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim() || !conversationId) return;

        const userMessage: Message = {
            id: Date.now().toString(),
            text: input,
            sender: 'user',
            timestamp: new Date()
        };

        setMessages(prev => [...prev, userMessage]);
        setInput('');
        setIsLoading(true);

        try {
            const response = await fetch('http://localhost:8000/tasks/new_task/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    demand: input,
                    conversation_id: conversationId,
                    skills_required: ['knowledge_retrieval']
                })
            });

            if (!response.ok) {
                throw new Error('Failed to assign task');
            }
        } catch (error) {
            console.error('Error:', error);
            setIsLoading(false);
        }
    };

    return (
        <div className='bg-[var(--bg)]'>
            <div className='max-w-4xl mx-auto p-4 min-h-[85vh] flex flex-col'>
                <div className='bg-[var(--bgSoft)] p-4 rounded-lg shadow-xl'>
                    <h1 className='text-2xl font-bold text-[var(--text)] flex items-center gap-2 justify-center'>
                        <Bot className='w-8 h-8 text-blue-500'/>
                        Horus Chat Assistant
                    </h1>
                </div>

                <div className='flex-1 overflow-y-auto p-4 space-y-4'>
                    {messages.length === 0 && (
                        <div className='text-center text-gray-500 mt-8'>
                            <Bot className='w-12 h-12 mx-auto mb-4 text-[var(--textSoft)]'/>
                            <p className='text-lg text-[var(--textSoft)]'>
                                Start a conversation with the agent
                            </p>
                            <p className='text-sm text-[var(--textSoft)]'>
                                How can we help you?
                            </p>
                        </div>
                    )}

                    {messages.map((message) => (
                        <div
                            key={message.id}
                            className={`flex ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                            <div
                                className={`flex gap-2 max-w-[80%]
                                    ${message.sender === 'user' ? 'flex-row-reverse' : 'flex-row'}
                                `}
                            >
                                <div className='w-8 h-8 rounded-full flex items-center justify-center bg-[var(--bgSoft)] text-[var(--text)]'>
                                    {message.sender === 'user' ?
                                        <User className='w-5 h-5'/>
                                        :
                                        <Bot className='w-5 h-5 text-blue-500'/>
                                    }
                                </div>
                                <div
                                    className={`rounded-lg p-3 text-[var(--text)] ${
                                        message.sender === 'user' 
                                            ? 'bg-blue-500 ml-auto' 
                                            : 'bg-[var(--bgSoft)] mr-auto'
                                    }`}
                                >
                                    {message.text}
                                </div>
                            </div>
                        </div>
                    ))}

                    {isLoading && (
                        <div className='flex justify-start'>
                            <div className='flex gap-2'>
                                <div className='w-8 h-8 rounded-full flex items-center justify-center bg-[var(--bgSoft)]'>
                                    <Bot className='w-5 h-5 text-blue-500'/>
                                </div>
                                <div className='bg-white border rounded-lg p-4'>
                                    <div className='flex gap-1'>
                                        <div className='w-2 h-2 bg-gray-400 rounded-full animate-bounce'/>
                                        <div className='w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.2s]'/>
                                        <div className='w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.4s]'/>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                <form
                    onSubmit={submit}
                    className='bg-[var(--bgSoft)] p-4 rounded-lg shadow-xl'
                >
                    <div className='flex gap-2'>
                        <input
                            type="text"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            placeholder='Type a message...'
                            className='flex-1 rounded-lg border border-[var(--textSoft)] p-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
                            disabled={!conversationId}
                        />
                        <button
                            type='submit'
                            disabled={!input.trim() || isLoading || !conversationId}
                            className='bg-blue-500 text-white p-2 rounded-lg px-4 py-2 transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-2'
                        >
                            <Send className='w-4 h-4'/>
                            Send
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default Chat;