/**
 * Smoke test / manual verifier for dsh-web-fetch-http-fakeip.
 *
 * It loads the real plugin, registers the provider through a stand-in `ctx.web`, and
 * fetches the URLs given on the command line — so a fake-ip environment can be checked
 * without installing anything into a profile.
 *
 *   # default ranges are Clash Verge's (198.18.0.1/16 and fdfe:dcba:9876::1/64)
 *   node test/smoke.mjs https://example.com/ https://www.google.com/
 *
 *   # explicit ranges, and the wrong ones to see the diagnostic
 *   node test/smoke.mjs --ranges 198.18.0.1/16,fdfe:dcba:9876::1/64 https://example.com/
 *   node test/smoke.mjs --ranges 10.0.0.0/8 https://example.com/
 *
 * `WEB_FETCH_FAKEIP_PEER_ROOT` (or the `DSH_`-prefixed spelling) is only needed when
 * the runtime's packages are not resolvable from this directory; a profile install
 * resolves them through the running dsh installation.
 */

import { apply, inject, name } from '../index.js'

const DEFAULT_RANGES = '198.18.0.1/16,fdfe:dcba:9876::1/64'

const args = process.argv.slice(2)
const takeFlag = (label, fallback) => {
  const index = args.indexOf(label)
  return index === -1 ? fallback : args.splice(index, 2)[1]
}
const fakeIpRanges = takeFlag('--ranges', DEFAULT_RANGES)
  .split(',')
  .map((entry) => entry.trim())
  .filter((entry) => entry !== '')
const urls = args.length > 0
  ? args
  : ['https://example.com/', 'https://deepseek-harness.github.io/deepseek-harness/guide/python-sdk']

const registered = new Map()
const ctx = {
  logger: { info: (message) => console.log(`[logger] ${message}`) },
  web: {
    registerFetchProvider(provider) {
      if (registered.has(provider.id)) {
        throw Object.assign(new Error(`duplicate ${provider.id}`), { code: 'WEB_DUPLICATE_PROVIDER' })
      }
      registered.set(provider.id, provider)
      return () => registered.delete(provider.id)
    },
  },
}

console.log(`plugin: name=${name} inject=[${inject.join(', ')}]`)
await apply(ctx, { fakeIpRanges, debug: true })

if (registered.size !== 1) throw new Error(`expected one registered provider, got ${registered.size}`)
const [id, provider] = [...registered.entries()][0]
console.log(`registered provider id=${id} available=${provider.available()}\n`)

let failures = 0
for (const url of urls) {
  try {
    const result = await provider.fetch({ url })
    const body = result.body.content ?? ''
    const title = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(body)?.[1]?.trim() ?? ''
    console.log(
      `OK   ${url} => HTTP ${result.statusCode} ${result.body.kind} chars=${body.length}` +
        (title === '' ? '' : ` title=${JSON.stringify(title)}`),
    )
  } catch (error) {
    failures += 1
    console.log(`FAIL ${url} => ${error.code ?? error.name}: ${error.message}`)
  }
}

console.log(`\n${urls.length - failures}/${urls.length} fetched`)
process.exitCode = failures === 0 ? 0 : 1
