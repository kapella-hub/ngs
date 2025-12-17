import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const API_URL = import.meta.env.VITE_API_URL || ''

export const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor for auth token
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor for auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Auth API
export const authApi = {
  login: async (username: string, password: string) => {
    const response = await api.post('/auth/login', { username, password })
    return response.data
  },

  me: async () => {
    const response = await api.get('/auth/me')
    return response.data
  },
}

// Incidents API
export const incidentsApi = {
  list: async (params: Record<string, any> = {}) => {
    const response = await api.get('/incidents', { params })
    return response.data
  },

  get: async (id: string) => {
    const response = await api.get(`/incidents/${id}`)
    return response.data
  },

  acknowledge: async (id: string, comment?: string) => {
    const response = await api.post(`/incidents/${id}/ack`, { comment })
    return response.data
  },

  resolve: async (id: string, comment?: string) => {
    const response = await api.post(`/incidents/${id}/resolve`, { comment })
    return response.data
  },

  suppress: async (id: string, data: { duration_minutes?: number; reason: string }) => {
    const response = await api.post(`/incidents/${id}/suppress`, data)
    return response.data
  },

  addComment: async (id: string, content: string) => {
    const response = await api.post(`/incidents/${id}/comment`, { content })
    return response.data
  },

  getComments: async (id: string) => {
    const response = await api.get(`/incidents/${id}/comments`)
    return response.data
  },

  getEvents: async (id: string, params: Record<string, any> = {}) => {
    const response = await api.get(`/incidents/${id}/events`, { params })
    return response.data
  },

  getRawEmail: async (incidentId: string, eventId: string) => {
    const response = await api.get(`/incidents/${incidentId}/raw-email/${eventId}`)
    return response.data
  },

  getMaintenance: async (id: string) => {
    const response = await api.get(`/incidents/${id}/maintenance`)
    return response.data
  },
}

// Maintenance API
export const maintenanceApi = {
  list: async (params: Record<string, any> = {}) => {
    const response = await api.get('/maintenance', { params })
    return response.data
  },

  get: async (id: string) => {
    const response = await api.get(`/maintenance/${id}`)
    return response.data
  },

  create: async (data: any) => {
    const response = await api.post('/maintenance', data)
    return response.data
  },

  update: async (id: string, data: any) => {
    const response = await api.patch(`/maintenance/${id}`, data)
    return response.data
  },

  delete: async (id: string) => {
    await api.delete(`/maintenance/${id}`)
  },

  getActive: async () => {
    const response = await api.get('/maintenance/active')
    return response.data
  },
}

// Quarantine API
export const quarantineApi = {
  list: async (params: Record<string, any> = {}) => {
    const response = await api.get('/quarantine', { params })
    return response.data
  },

  get: async (id: string) => {
    const response = await api.get(`/quarantine/${id}`)
    return response.data
  },

  retry: async (id: string) => {
    const response = await api.post(`/quarantine/${id}/retry`)
    return response.data
  },

  stats: async () => {
    const response = await api.get('/quarantine/stats')
    return response.data
  },
}

// Admin API
export const adminApi = {
  getConfig: async (type: string) => {
    const response = await api.get(`/admin/config/${type}`)
    return response.data
  },

  uploadConfig: async (type: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post(`/admin/config/upload?config_type=${type}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  },

  reloadConfig: async () => {
    const response = await api.post('/admin/reload-config')
    return response.data
  },

  getIngestionStatus: async () => {
    const response = await api.get('/admin/ingestion/status')
    return response.data
  },

  getAuditLog: async (params: Record<string, any> = {}) => {
    const response = await api.get('/admin/audit-log', { params })
    return response.data
  },

  getStats: async () => {
    const response = await api.get('/admin/stats/overview')
    return response.data
  },

  getSeverityBreakdown: async () => {
    const response = await api.get('/admin/stats/severity')
    return response.data
  },

  getSourceBreakdown: async () => {
    const response = await api.get('/admin/stats/sources')
    return response.data
  },
}
