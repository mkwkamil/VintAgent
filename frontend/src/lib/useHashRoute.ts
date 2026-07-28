import { useCallback, useEffect, useState } from 'react'

/**
 * Minimal hash router: the dashboard has exactly two views, so a routing
 * library would be all cost and no benefit. Using the hash (rather than a
 * useState) keeps the browser back button and page reloads working.
 */
export function useHashRoute(): { detailId: string | null; openDetail: (id: string) => void; goBack: () => void } {
  const [hash, setHash] = useState(() => window.location.hash)

  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  const match = /^#\/url\/([\w-]+)$/.exec(hash)

  const openDetail = useCallback((id: string) => {
    window.location.hash = `#/url/${id}`
  }, [])

  const goBack = useCallback(() => {
    // history.back() would leave the app if the detail view was opened directly
    // from a bookmark, so fall back to rewriting the hash.
    if (window.history.length > 1) window.history.back()
    else window.location.hash = ''
  }, [])

  return { detailId: match ? match[1] : null, openDetail, goBack }
}
