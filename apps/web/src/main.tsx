import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)


/**
 * Register the service worker.
 *
 * Registered after load so it never competes with the first paint for
 * bandwidth. On a 2G connection the first render is what matters; offline
 * support is worth nothing to someone who never got the app to open.
 *
 * Failures are expected in several ordinary situations -- private browsing,
 * plain HTTP, and embedded or preview browsers that disable service workers
 * outright -- and none of them is a reason to show a farmer an error about a
 * caching layer they did not ask for.
 *
 * But they are logged rather than swallowed. An earlier version silently
 * discarded the error, and diagnosing why registration was not happening
 * then took three round-trips of manual probing to establish that the script
 * was being served correctly and the environment was blocking it. A
 * console line would have said so immediately.
 */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((reg) => {
        if (import.meta.env.DEV) {
          console.info('[agrin] service worker registered', reg.scope)
        }
      })
      .catch((err) => {
        // Visible to a developer, invisible to a farmer.
        console.warn(
          '[agrin] service worker did not register; offline support is off. ' +
          'This is normal in private browsing, over plain HTTP, and in ' +
          'embedded preview browsers.',
          err,
        )
      })
  })
}
