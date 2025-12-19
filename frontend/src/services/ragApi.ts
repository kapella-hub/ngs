// In production (Docker), use /rag proxy. In dev, use direct URL.
const RAG_API_URL = import.meta.env.DEV
  ? (import.meta.env.VITE_RAG_URL || 'http://localhost:8001')
  : '/rag'

interface RagStats {
  document_count: number
}

interface RagHealth {
  status: string
}

interface AskResponse {
  answer: string
  images?: string[]
}

interface DocumentFile {
  filename: string
  upload_date: string
  chunk_count: number
}

interface DocumentListResponse {
  files: DocumentFile[]
  total_files: number
}

interface UploadResponse {
  success_count: number
  failed_count: number
  total_chunks: number
}

interface UrlUploadResponse {
  success: boolean
  job_id?: string
  urls_processed?: number
  urls_failed?: number
  total_chunks: number
  error?: string
  cancelled?: boolean
}

export const ragApi = {
  async getHealth(): Promise<RagHealth> {
    const response = await fetch(`${RAG_API_URL}/health`)
    if (!response.ok) throw new Error('RAG service unavailable')
    return response.json()
  },

  async getStats(): Promise<RagStats> {
    const response = await fetch(`${RAG_API_URL}/stats`)
    if (!response.ok) throw new Error('Failed to fetch stats')
    return response.json()
  },

  async ask(query: string): Promise<AskResponse> {
    const response = await fetch(`${RAG_API_URL}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to get answer')
    }
    return response.json()
  },

  async listDocuments(): Promise<DocumentListResponse> {
    const response = await fetch(`${RAG_API_URL}/documents/list`)
    if (!response.ok) throw new Error('Failed to list documents')
    return response.json()
  },

  async uploadDocuments(files: File[]): Promise<UploadResponse> {
    const formData = new FormData()
    files.forEach(file => formData.append('files', file))

    const response = await fetch(`${RAG_API_URL}/documents/upload`, {
      method: 'POST',
      body: formData
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Upload failed')
    }
    return response.json()
  },

  async uploadUrl(
    url: string,
    options?: { followLinks?: boolean; maxDepth?: number; sameDomainOnly?: boolean }
  ): Promise<UrlUploadResponse> {
    const response = await fetch(`${RAG_API_URL}/documents/upload-url`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url,
        follow_links: options?.followLinks || false,
        max_depth: options?.maxDepth || 2,
        same_domain_only: options?.sameDomainOnly ?? true
      })
    })
    const data = await response.json()
    if (!response.ok && !data.cancelled) {
      throw new Error(data.detail || data.error || 'Failed to add URL')
    }
    return data
  },

  async deleteDocument(filename: string): Promise<void> {
    const response = await fetch(
      `${RAG_API_URL}/documents/file/${encodeURIComponent(filename)}`,
      { method: 'DELETE' }
    )
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to delete document')
    }
  },

  async refreshUrl(url: string): Promise<{ success: boolean; total_chunks: number }> {
    const response = await fetch(
      `${RAG_API_URL}/documents/refresh-url/${encodeURIComponent(url)}`,
      { method: 'POST' }
    )
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.detail || data.error || 'Failed to refresh URL')
    }
    return data
  },

  async clearAllDocuments(): Promise<void> {
    const response = await fetch(`${RAG_API_URL}/documents/clear`, {
      method: 'DELETE'
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to clear documents')
    }
  },

  async cancelIngestion(jobId: string): Promise<{ success: boolean; message: string }> {
    const response = await fetch(
      `${RAG_API_URL}/documents/cancel-ingestion/${jobId}`,
      { method: 'POST' }
    )
    return response.json()
  }
}
