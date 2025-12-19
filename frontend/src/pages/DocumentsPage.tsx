import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeftIcon,
  CloudArrowUpIcon,
  TrashIcon,
  ArrowPathIcon,
  GlobeAltIcon,
  DocumentIcon,
  MagnifyingGlassIcon
} from '@heroicons/react/24/outline'
import { ragApi } from '../services/ragApi'

interface DocumentFile {
  filename: string
  upload_date: string
  chunk_count: number
}

export default function DocumentsPage() {
  const [files, setFiles] = useState<DocumentFile[]>([])
  const [filteredFiles, setFilteredFiles] = useState<DocumentFile[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
  const [urlInput, setUrlInput] = useState('')
  const [urlStatus, setUrlStatus] = useState<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
  const [isAddingUrl, setIsAddingUrl] = useState(false)
  const [followLinks, setFollowLinks] = useState(false)
  const [maxDepth, setMaxDepth] = useState(2)
  const [sameDomainOnly, setSameDomainOnly] = useState(true)
  const [stats, setStats] = useState({ fileCount: 0, chunkCount: 0, isOnline: false })
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const itemsPerPage = 10

  const loadFiles = useCallback(async () => {
    try {
      const data = await ragApi.listDocuments()
      setFiles(data.files)
      setFilteredFiles(data.files)
      const totalChunks = data.files.reduce((sum, f) => sum + f.chunk_count, 0)
      setStats(prev => ({
        ...prev,
        fileCount: data.total_files,
        chunkCount: totalChunks
      }))
    } catch (error) {
      console.error('Failed to load files:', error)
    } finally {
      setIsLoading(false)
    }
  }, [])

  const checkHealth = useCallback(async () => {
    try {
      const health = await ragApi.getHealth()
      setStats(prev => ({ ...prev, isOnline: health.status === 'healthy' }))
    } catch {
      setStats(prev => ({ ...prev, isOnline: false }))
    }
  }, [])

  useEffect(() => {
    loadFiles()
    checkHealth()
  }, [loadFiles, checkHealth])

  useEffect(() => {
    if (!searchQuery.trim()) {
      setFilteredFiles(files)
    } else {
      const query = searchQuery.toLowerCase()
      setFilteredFiles(files.filter(f => f.filename.toLowerCase().includes(query)))
    }
    setCurrentPage(1)
  }, [searchQuery, files])

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files))
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const droppedFiles = Array.from(e.dataTransfer.files)
    setSelectedFiles(droppedFiles)
  }

  const handleUpload = async () => {
    if (selectedFiles.length === 0) return

    setIsUploading(true)
    setUploadStatus({ type: 'info', message: 'Uploading and processing documents...' })

    try {
      const result = await ragApi.uploadDocuments(selectedFiles)
      setUploadStatus({
        type: 'success',
        message: `Successfully uploaded ${result.success_count} file(s). Created ${result.total_chunks} chunks.${
          result.failed_count > 0 ? ` ${result.failed_count} file(s) failed.` : ''
        }`
      })
      setSelectedFiles([])
      if (fileInputRef.current) fileInputRef.current.value = ''
      loadFiles()
    } catch (error) {
      setUploadStatus({
        type: 'error',
        message: error instanceof Error ? error.message : 'Upload failed'
      })
    } finally {
      setIsUploading(false)
    }
  }

  const handleAddUrl = async () => {
    if (!urlInput.trim()) {
      setUrlStatus({ type: 'error', message: 'Please enter a URL' })
      return
    }

    if (!urlInput.startsWith('http://') && !urlInput.startsWith('https://')) {
      setUrlStatus({ type: 'error', message: 'URL must start with http:// or https://' })
      return
    }

    setIsAddingUrl(true)
    setUrlStatus({
      type: 'info',
      message: followLinks
        ? `Crawling URL and following links (depth: ${maxDepth})...`
        : 'Fetching and processing URL content...'
    })

    try {
      const result = await ragApi.uploadUrl(urlInput, { followLinks, maxDepth, sameDomainOnly })

      if (result.cancelled) {
        setUrlStatus({ type: 'info', message: `Operation cancelled. ${result.urls_processed || 0} URLs were processed.` })
      } else if (result.success) {
        setUrlStatus({
          type: 'success',
          message: `Successfully added URL! URLs processed: ${result.urls_processed || 1}, Chunks created: ${result.total_chunks}`
        })
        setUrlInput('')
        loadFiles()
      } else {
        throw new Error(result.error || 'Failed to add URL')
      }
    } catch (error) {
      setUrlStatus({
        type: 'error',
        message: error instanceof Error ? error.message : 'Failed to add URL'
      })
    } finally {
      setIsAddingUrl(false)
    }
  }

  const handleDelete = async (filename: string) => {
    if (!confirm(`Delete "${filename}" and all its data?`)) return

    try {
      await ragApi.deleteDocument(filename)
      loadFiles()
    } catch (error) {
      alert(error instanceof Error ? error.message : 'Failed to delete')
    }
  }

  const handleRefresh = async (url: string) => {
    if (!confirm(`Refresh content from:\n${url}\n\nThis will re-fetch the latest content.`)) return

    try {
      const result = await ragApi.refreshUrl(url)
      alert(`Successfully refreshed! Created ${result.total_chunks} chunks.`)
      loadFiles()
    } catch (error) {
      alert(error instanceof Error ? error.message : 'Failed to refresh')
    }
  }

  const handleClearAll = async () => {
    if (!confirm('⚠️ This will permanently delete ALL documents. Are you sure?')) return

    try {
      await ragApi.clearAllDocuments()
      loadFiles()
    } catch (error) {
      alert(error instanceof Error ? error.message : 'Failed to clear')
    }
  }

  const formatDate = (isoDate: string) => {
    if (!isoDate || isoDate === 'unknown') return 'Unknown'
    try {
      return new Date(isoDate).toLocaleString()
    } catch {
      return isoDate
    }
  }

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  // Pagination
  const totalPages = Math.ceil(filteredFiles.length / itemsPerPage)
  const paginatedFiles = filteredFiles.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  )

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/knowledge" className="p-2 hover:bg-gray-100 rounded-lg transition">
            <ArrowLeftIcon className="h-5 w-5 text-gray-600" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Manage Documents</h1>
            <p className="text-sm text-gray-500">Upload and manage knowledge base documents</p>
          </div>
        </div>
      </div>

      {/* Stats bar */}
      <div className="mb-6 bg-white rounded-lg shadow p-4 flex items-center justify-between">
        <div className="flex items-center gap-8">
          <div>
            <div className="text-2xl font-bold text-primary-600">{stats.fileCount}</div>
            <div className="text-xs text-gray-500">Total Files</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-primary-600">{stats.chunkCount}</div>
            <div className="text-xs text-gray-500">Total Chunks</div>
          </div>
          <div>
            <div className={`text-xl ${stats.isOnline ? 'text-green-500' : 'text-red-500'}`}>
              {stats.isOnline ? '● Online' : '● Offline'}
            </div>
          </div>
        </div>
        <button
          onClick={handleClearAll}
          className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition flex items-center gap-2"
        >
          <TrashIcon className="h-5 w-5" />
          Clear All
        </button>
      </div>

      {/* Upload section */}
      <div className="mb-6 bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <CloudArrowUpIcon className="h-6 w-6 text-primary-600" />
          Upload Documents
        </h2>

        <div
          className="border-2 border-dashed border-primary-300 rounded-lg p-8 text-center cursor-pointer hover:border-primary-500 transition bg-gray-50"
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <CloudArrowUpIcon className="h-12 w-12 mx-auto text-primary-400 mb-3" />
          <p className="font-medium text-gray-700">Drag & drop files here</p>
          <p className="text-sm text-gray-500 mt-1">or click to browse</p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            accept=".txt,.md,.pdf,.docx,.pptx,.xls,.xlsx,.html,.htm,.csv,.png,.jpg,.jpeg,.tif,.tiff"
            onChange={handleFileSelect}
          />
        </div>

        {selectedFiles.length > 0 && (
          <div className="mt-4">
            <div className="space-y-2 mb-4">
              {selectedFiles.map((file, idx) => (
                <div key={idx} className="flex items-center justify-between bg-gray-100 px-4 py-2 rounded">
                  <span className="text-sm">{file.name}</span>
                  <span className="text-xs text-gray-500">{formatFileSize(file.size)}</span>
                </div>
              ))}
            </div>
            <button
              onClick={handleUpload}
              disabled={isUploading}
              className="w-full py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition"
            >
              {isUploading ? 'Uploading...' : 'Upload Files'}
            </button>
          </div>
        )}

        {uploadStatus && (
          <div className={`mt-4 p-3 rounded ${
            uploadStatus.type === 'success' ? 'bg-green-100 text-green-800' :
            uploadStatus.type === 'error' ? 'bg-red-100 text-red-800' :
            'bg-blue-100 text-blue-800'
          }`}>
            {uploadStatus.message}
          </div>
        )}
      </div>

      {/* URL section */}
      <div className="mb-6 bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <GlobeAltIcon className="h-6 w-6 text-primary-600" />
          Add from URL
        </h2>

        <div className="flex gap-3 mb-4">
          <input
            type="url"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            placeholder="Enter URL (e.g., https://example.com/docs)"
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none"
          />
          <button
            onClick={handleAddUrl}
            disabled={isAddingUrl}
            className="px-6 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition"
          >
            {isAddingUrl ? 'Adding...' : 'Add URL'}
          </button>
        </div>

        <div className="bg-gray-50 p-4 rounded-lg">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={followLinks}
              onChange={(e) => setFollowLinks(e.target.checked)}
              className="w-4 h-4"
            />
            <span className="text-sm text-gray-700">Follow and ingest links found on the page</span>
          </label>

          {followLinks && (
            <div className="mt-3 ml-6 space-y-3">
              <div className="flex items-center gap-3">
                <label className="text-sm text-gray-600">Max depth:</label>
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={maxDepth}
                  onChange={(e) => setMaxDepth(parseInt(e.target.value) || 2)}
                  className="w-16 px-2 py-1 border border-gray-300 rounded"
                />
                <span className="text-xs text-gray-500">(1-5)</span>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={sameDomainOnly}
                  onChange={(e) => setSameDomainOnly(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-sm text-gray-700">Only follow links within same domain</span>
              </label>
            </div>
          )}
        </div>

        {urlStatus && (
          <div className={`mt-4 p-3 rounded ${
            urlStatus.type === 'success' ? 'bg-green-100 text-green-800' :
            urlStatus.type === 'error' ? 'bg-red-100 text-red-800' :
            'bg-blue-100 text-blue-800'
          }`}>
            {urlStatus.message}
          </div>
        )}
      </div>

      {/* Files list */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <DocumentIcon className="h-6 w-6 text-primary-600" />
          Uploaded Files
        </h2>

        {/* Search */}
        <div className="mb-4 relative">
          <MagnifyingGlassIcon className="h-5 w-5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search documents..."
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none"
          />
        </div>

        {isLoading ? (
          <div className="text-center py-8 text-gray-500">Loading...</div>
        ) : filteredFiles.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <DocumentIcon className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>{searchQuery ? 'No files match your search' : 'No files uploaded yet'}</p>
          </div>
        ) : (
          <>
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-600">Filename</th>
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-600">Upload Date</th>
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-600">Chunks</th>
                  <th className="text-right py-3 px-4 text-sm font-semibold text-gray-600">Actions</th>
                </tr>
              </thead>
              <tbody>
                {paginatedFiles.map((file) => {
                  const isUrl = file.filename.startsWith('http://') || file.filename.startsWith('https://')
                  return (
                    <tr key={file.filename} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          {isUrl ? (
                            <GlobeAltIcon className="h-5 w-5 text-blue-500" />
                          ) : (
                            <DocumentIcon className="h-5 w-5 text-gray-400" />
                          )}
                          <span className="text-sm font-medium truncate max-w-[300px]" title={file.filename}>
                            {file.filename}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-4 text-sm text-gray-600">{formatDate(file.upload_date)}</td>
                      <td className="py-3 px-4 text-sm text-gray-600">{file.chunk_count}</td>
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {isUrl && (
                            <button
                              onClick={() => handleRefresh(file.filename)}
                              className="p-2 text-green-600 hover:bg-green-50 rounded transition"
                              title="Refresh URL content"
                            >
                              <ArrowPathIcon className="h-5 w-5" />
                            </button>
                          )}
                          <button
                            onClick={() => handleDelete(file.filename)}
                            className="p-2 text-red-600 hover:bg-red-50 rounded transition"
                            title="Delete"
                          >
                            <TrashIcon className="h-5 w-5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="mt-4 flex items-center justify-center gap-2">
                <button
                  onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="px-3 py-1 border rounded disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="text-sm text-gray-600">
                  Page {currentPage} of {totalPages}
                </span>
                <button
                  onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages}
                  className="px-3 py-1 border rounded disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
