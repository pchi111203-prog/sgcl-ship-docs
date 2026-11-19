// Thin fetch wrapper: adds the session token and turns API errors into readable messages.
export const auth = {
  get token() { try { return localStorage.getItem('sgcl.token') } catch { return null } },
  set token(v) { try { v ? localStorage.setItem('sgcl.token', v) : localStorage.removeItem('sgcl.token') } catch { /* ignore */ } },
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : detail?.message || 'Lỗi hệ thống')
    this.status = status
    this.detail = detail
  }
}

export async function api(path, { method = 'GET', body, form } = {}) {
  const headers = {}
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const r = await fetch(path, { method, headers, body: payload })
  if (r.status === 401 && !path.endsWith('/login')) {
    auth.token = null
    window.location.href = '/login'
    throw new ApiError(401, 'Phiên đăng nhập hết hạn')
  }
  const ct = r.headers.get('content-type') || ''
  const data = ct.includes('json') ? await r.json() : await r.text()
  if (!r.ok) throw new ApiError(r.status, data?.detail ?? data)
  return data
}

export const fileUrl = (path) => `${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(auth.token || '')}`

export const fmtSize = (n) => n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
