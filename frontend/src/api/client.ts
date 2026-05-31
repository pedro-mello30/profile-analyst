import axios from 'axios'

export const client = axios.create({ baseURL: '/api' })

client.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('pa_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      sessionStorage.removeItem('pa_token')
      window.location.reload()
    }
    return Promise.reject(err)
  }
)
