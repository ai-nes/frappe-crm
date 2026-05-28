import { io } from 'socket.io-client'
import { getCachedListResource, getCachedResource } from 'frappe-ui'

export function initSocket() {
  let host = window.location.hostname
  let siteName = window.site_name
  // In standalone frontend mode, sites/common_site_config.json may not exist.
  // Prefer boot data from window, then fall back to default socketio port.
  let socketioPort = window.socketio_port || 9000
  let port = window.location.port ? `:${socketioPort}` : ''
  let protocol = port ? 'http' : 'https'
  let url = `${protocol}://${host}${port}/${siteName}`

  let socket = io(url, {
    withCredentials: true,
    reconnectionAttempts: 5,
  })
  socket.on('refetch_resource', (data) => {
    if (data.cache_key) {
      let resource =
        getCachedResource(data.cache_key) ||
        getCachedListResource(data.cache_key)
      if (resource) {
        resource.reload()
      }
    }
  })
  return socket
}
