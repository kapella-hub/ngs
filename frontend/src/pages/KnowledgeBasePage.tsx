import { useState, useEffect, useRef, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { PaperAirplaneIcon, DocumentTextIcon } from '@heroicons/react/24/outline'
import { ragApi } from '../services/ragApi'

interface Message {
  role: 'user' | 'assistant'
  content: string
  images?: string[]
}

export default function KnowledgeBasePage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [stats, setStats] = useState<{ documentCount: number; isOnline: boolean }>({
    documentCount: 0,
    isOnline: false
  })
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const health = await ragApi.getHealth()
        const statsData = await ragApi.getStats()
        setStats({
          documentCount: statsData.document_count || 0,
          isOnline: health.status === 'healthy'
        })
      } catch {
        setStats(prev => ({ ...prev, isOnline: false }))
      }
    }
    checkHealth()
    const interval = setInterval(checkHealth, 30000)
    return () => clearInterval(interval)
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setIsLoading(true)

    try {
      const response = await ragApi.ask(userMessage)
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: response.answer, images: response.images }
      ])
    } catch (error) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `Error: ${error instanceof Error ? error.message : 'Unknown error'}` }
      ])
    } finally {
      setIsLoading(false)
    }
  }

  const formatMarkdown = (text: string) => {
    // Simple markdown formatting
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code class="bg-gray-700 px-1 rounded">$1</code>')
      .replace(/\n/g, '<br />')
  }

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header with stats */}
      <div className="mb-6 bg-white rounded-lg shadow p-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Knowledge Base</h1>
            <p className="text-sm text-gray-500">
              Ask questions about your documentation and runbooks
            </p>
          </div>
          <div className="flex items-center gap-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-primary-600">{stats.documentCount}</div>
              <div className="text-xs text-gray-500">Chunks Indexed</div>
            </div>
            <div className="text-center">
              <div className={`text-2xl ${stats.isOnline ? 'text-green-500' : 'text-red-500'}`}>
                {stats.isOnline ? '●' : '●'}
              </div>
              <div className="text-xs text-gray-500">
                {stats.isOnline ? 'Online' : 'Offline'}
              </div>
            </div>
            <Link
              to="/documents"
              className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition"
            >
              <DocumentTextIcon className="h-5 w-5" />
              Manage Docs
            </Link>
          </div>
        </div>
      </div>

      {/* Chat container */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {/* Messages area */}
        <div className="h-[500px] overflow-y-auto p-4 bg-gray-50">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-gray-400">
              <svg className="h-16 w-16 mb-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
              <p className="text-lg">Ask a question about your documentation</p>
              <p className="text-sm mt-2">Upload documents via "Manage Docs" to get started</p>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg px-4 py-3 ${
                      message.role === 'user'
                        ? 'bg-primary-600 text-white'
                        : 'bg-white border border-gray-200 text-gray-800'
                    }`}
                  >
                    <div className="text-xs font-semibold mb-1 opacity-70">
                      {message.role === 'user' ? 'You' : 'Assistant'}
                    </div>
                    <div
                      className="prose prose-sm max-w-none"
                      dangerouslySetInnerHTML={{ __html: formatMarkdown(message.content) }}
                    />
                    {message.images && message.images.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {message.images.map((imgUrl, imgIndex) => (
                          <img
                            key={imgIndex}
                            src={imgUrl}
                            alt="Related"
                            className="max-w-[200px] max-h-[200px] rounded border border-gray-300 cursor-pointer hover:opacity-80"
                            onClick={() => window.open(imgUrl, '_blank')}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className="flex justify-start">
                  <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="animate-spin h-4 w-4 border-2 border-primary-600 border-t-transparent rounded-full" />
                      <span className="text-gray-500">Thinking...</span>
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input area */}
        <form onSubmit={handleSubmit} className="p-4 border-t border-gray-200 bg-white">
          <div className="flex gap-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your documents..."
              className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center gap-2"
            >
              <PaperAirplaneIcon className="h-5 w-5" />
              Send
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
