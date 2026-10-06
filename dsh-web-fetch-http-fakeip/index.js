/**
 * dsh-web-fetch-http-fakeip — keep `web_fetch` working while Clash/mihomo fake-ip DNS
 * is active, by accepting the fake-ip ranges the TUN device actually routes.
 *
 * ## The problem
 *
 * The shipped provider (`@deepseek-ai/dsh-web-fetch-http`) resolves every hostname
 * itself and rejects the whole answer set unless every address is public unicast.
 * Under fake-ip DNS the answers are the Clash-internal addresses (`198.18.0.0/15`,
 * `fdfe:dcba:9876::/64`, `2001:2::/48`, ...), so every fetch is refused with
 * `WEB_BLOCKED_URL` before a connection is attempted — even though the TUN device
 * would map that address back to the hostname and route the request normally, which
 * is exactly how `curl` keeps working.
 *
 * ## The change
 *
 * Accept a non-public answer when every such address falls inside a configured
 * fake-ip range. The connection still goes to the fake address; the TUN maps it back
 * to the hostname, so TLS SNI, Host, and Clash's rule routing are all unaffected.
 *
 * Two properties keep the change small and auditable:
 *
 * - The shipped provider exposes its resolver as the public field `resolveAddresses`.
 *   This plugin wraps that field instead of reimplementing the transport, so the
 *   shipped `requestOnce`, `followAndRead`, redirect and same-origin rules, byte and
 *   character caps, content-type decoding, address pinning, and deadline all stay in
 *   force. Nothing overrides a class method.
 * - The shipped resolver runs first and its result is returned untouched. Only a
 *   `WEB_BLOCKED_URL` refusal reaches the range check, and a refusal that the ranges
 *   do not cover is rethrown unchanged, so the seam's error vocabulary, the message
 *   the model sees, and every other non-public range (private, loopback, link-local,
 *   CGNAT, Teredo) keep their shipped behaviour.
 *
 * An IP literal is never accepted through a range: the address is already stated, so
 * a range exception could only launder `http://127.0.0.1:...` or `http://10.0.0.5/`.
 *
 * @module dsh-web-fetch-http-fakeip
 */

import { lookup } from 'node:dns/promises'
import { isIP } from 'node:net'
import { createRequire } from 'node:module'
import { basename, dirname, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

/** Cordis plugin name used in loader diagnostics. */
export const name = 'web-fetch-http-fakeip'

/** The capability seam this plugin registers into. */
export const inject = ['web']

/**
 * Runtime packages this plugin borrows.
 *
 * The module's own top level intentionally imports `node:` builtins only: an
 * out-of-tree plugin cannot statically resolve the runtime's packages from the
 * profile directory, so those imports happen through {@link importRuntimePackage}.
 */
const PEER_PACKAGE = '@deepseek-ai/dsh-web-fetch-http'
const IPADDR_PACKAGE = 'ipaddr.js'

/**
 * Optional node_modules root used when the runtime's packages cannot be resolved.
 * The `DSH_`-prefixed name is bootstrap-only, so it cannot come from a `.env` file;
 * the unprefixed name exists so it can live in `$DSH_HOME/.env`.
 */
const PEER_ROOT_ENV = 'DSH_WEB_FETCH_FAKEIP_PEER_ROOT'
const PEER_ROOT_ENV_ALT = 'WEB_FETCH_FAKEIP_PEER_ROOT'

/** Codes the web seam routes on, kept as strings so no cross-package class identity is needed. */
const CODE_BLOCKED_URL = 'WEB_BLOCKED_URL'
const CODE_DUPLICATE_PROVIDER = 'WEB_DUPLICATE_PROVIDER'

/** Node coerces larger timer delays to 1 ms, so the shipped provider caps this field. */
const MAX_NODE_TIMER_DELAY_MS = 2147483647

/** Transport limits mirroring the shipped provider's defaults, so disabling its row loses no configuration. */
const DEFAULT_LIMITS = {
  maxResponseBytes: 5e6,
  maxBodyChars: 1e5,
  timeoutMs: 3e4,
  maxRedirects: 5,
}

/**
 * Candidate resolution anchors, in order.
 *
 * The running dsh entry (`process.argv[1]`) sits inside the installation's dependency
 * tree, so walking up from it finds the host's own module instances. Sharing the
 * host's instances matters: the shipped transport asks `dsh-http-proxy` for the
 * process-wide proxy policy, which only the host's copy has.
 *
 * @returns absolute `createRequire` anchor files, most specific first.
 */
function resolutionAnchors() {
  const anchors = []
  const entry = process.argv[1]
  if (typeof entry === 'string' && entry !== '') {
    let dir = dirname(resolve(entry))
    for (let depth = 0; depth < 8; depth += 1) {
      anchors.push(join(dir, 'noop.cjs'))
      const parent = dirname(dir)
      if (parent === dir) break
      dir = parent
    }
  }
  const root = (process.env[PEER_ROOT_ENV] ?? process.env[PEER_ROOT_ENV_ALT])?.trim()
  if (root !== undefined && root !== '') {
    // The variable names a node_modules directory, so the anchor has to sit beside it.
    anchors.push(join(basename(root) === 'node_modules' ? dirname(root) : root, 'noop.cjs'))
  }
  return anchors
}

/**
 * Import a runtime-provided package.
 *
 * Resolution order: the normal bare specifier (source trees, and carriers that
 * project the runtime's packages into the profile), then the running dsh
 * installation, then the peer-root environment variable.
 *
 * @param specifier - bare package specifier.
 * @returns the imported module namespace.
 */
async function importRuntimePackage(specifier) {
  let directError
  try {
    return await import(specifier)
  } catch (error) {
    directError = error
  }

  for (const anchor of resolutionAnchors()) {
    try {
      const resolveFromAnchor = createRequire(anchor)
      return await import(pathToFileURL(resolveFromAnchor.resolve(specifier)).href)
    } catch {
      // Try the next anchor.
    }
  }

  throw new Error(
    `dsh-web-fetch-http-fakeip: cannot load ${specifier} (${directError?.message ?? 'no resolution anchor worked'}). ` +
      `Set ${PEER_ROOT_ENV} (export it) or ${PEER_ROOT_ENV_ALT} (allowed in $DSH_HOME/.env) ` +
      `to the dsh runtime's node_modules directory.`,
  )
}

/**
 * Resolve the CommonJS default export shape of a dynamically imported package.
 *
 * @param module - imported namespace.
 * @returns the CJS module object when one is present, else the namespace.
 */
function commonJsDefault(module) {
  return module?.default ?? module
}

/**
 * Strip the brackets `URL.hostname` keeps on an IPv6 literal.
 *
 * @param hostname - URL hostname.
 * @returns the bare address text.
 */
function unbracket(hostname) {
  return hostname.startsWith('[') && hostname.endsWith(']') ? hostname.slice(1, -1) : hostname
}

/**
 * Validate the configured range list.
 *
 * @param value - `config.fakeIpRanges`.
 * @returns the non-empty range strings.
 * @throws when the value is not a list of non-empty strings.
 */
function normalizeRangeConfig(value) {
  if (value === undefined) return []
  if (!Array.isArray(value)) {
    throw new Error('dsh-web-fetch-http-fakeip: fakeIpRanges must be a list of CIDR strings')
  }
  return value.map((entry) => {
    if (typeof entry !== 'string' || entry.trim() === '') {
      throw new Error(
        `dsh-web-fetch-http-fakeip: fakeIpRanges entries must be non-empty CIDR strings, got ${JSON.stringify(entry)}`,
      )
    }
    return entry.trim()
  })
}

/**
 * Parse CIDR strings into same-family matchers.
 *
 * @param texts - validated CIDR strings.
 * @param ipaddr - the `ipaddr.js` module.
 * @returns one entry per range, with its family and parsed CIDR.
 * @throws when a range is not a valid CIDR.
 */
function parseRanges(texts, ipaddr) {
  return texts.map((text) => {
    let address
    let prefix
    try {
      ;[address, prefix] = ipaddr.parseCIDR(text)
    } catch (error) {
      throw new Error(
        `dsh-web-fetch-http-fakeip: fakeIpRanges entry is not a CIDR (write it as Clash does, e.g. 198.18.0.1/16): ${text} (${error.message})`,
      )
    }
    return { text, family: address.kind() === 'ipv4' ? 4 : 6, cidr: [address, prefix] }
  })
}

/**
 * Classify one address as globally reachable unicast, mirroring the shipped guard.
 *
 * @param address - textual address.
 * @param ipaddr - the `ipaddr.js` module.
 * @returns true only for a public unicast destination.
 */
function isPublicUnicast(address, ipaddr) {
  let parsed
  try {
    parsed = ipaddr.parse(unbracket(address))
  } catch {
    return false
  }
  // `isIPv4MappedAddress` exists on IPv6 instances only; mirror the shipped guard's order.
  if (parsed.kind() === 'ipv6' && parsed.isIPv4MappedAddress()) parsed = parsed.toIPv4Address()
  return parsed.range() === 'unicast'
}

/**
 * Return the configured range an address falls in, if any.
 *
 * @param address - textual address.
 * @param ranges - parsed ranges.
 * @param ipaddr - the `ipaddr.js` module.
 * @returns the matching range text, or undefined.
 */
function matchingRange(address, ranges, ipaddr) {
  let parsed
  try {
    parsed = ipaddr.parse(unbracket(address))
  } catch {
    return undefined
  }
  if (parsed.kind() === 'ipv6' && parsed.isIPv4MappedAddress()) parsed = parsed.toIPv4Address()
  const family = parsed.kind() === 'ipv4' ? 4 : 6
  for (const range of ranges) {
    if (range.family !== family) continue
    if (parsed.match(range.cidr)) return range.text
  }
  return undefined
}

/**
 * Build a resolver that accepts non-public answers only when they come from the
 * configured fake-ip ranges.
 *
 * The shipped resolver runs first and its result is returned untouched. A refusal it
 * does not report as `WEB_BLOCKED_URL`, a literal host, and an answer set with any
 * address outside the ranges all rethrow the shipped error object unchanged, so the
 * seam sees exactly what it would see without this plugin.
 *
 * @param options - original resolver, parsed ranges, ipaddr module, and diagnostics flag.
 * @returns a resolver with the shipped `resolveAddresses` signature.
 */
function createRangeResolver({ original, ranges, ipaddr, debug }) {
  const rangeText = ranges.map((range) => range.text).join(', ')
  // A regular function, so the call site's `this` (the provider) reaches the shipped resolver.
  return async function resolveWithFakeIpRanges(hostname, signal) {
    let blocked
    try {
      return await original.call(this, hostname, signal)
    } catch (error) {
      if (error?.code !== CODE_BLOCKED_URL) throw error
      blocked = error
    }

    const target = unbracket(hostname)
    if (isIP(target) !== 0) {
      // A literal already states its destination; a range exception could only
      // launder a private address. Keep the shipped refusal.
      throw blocked
    }

    const answers = await lookup(target, { all: true, order: 'verbatim' })
    if (answers.length === 0) throw blocked

    const rejected = answers.filter(
      (answer) => !isPublicUnicast(answer.address, ipaddr) && matchingRange(answer.address, ranges, ipaddr) === undefined,
    )
    if (rejected.length > 0) {
      if (debug) {
        process.stderr.write(
          `dsh-web-fetch-http-fakeip: refused ${target}: ${rejected.map((answer) => answer.address).join(', ')} outside ${rangeText}\n`,
        )
      }
      throw blocked
    }

    if (debug) {
      process.stderr.write(
        `dsh-web-fetch-http-fakeip: accepted ${target} from fake-ip ranges: ${answers.map((answer) => answer.address).join(', ')}\n`,
      )
    }
    return answers.map((answer) => ({ address: answer.address, family: answer.family }))
  }
}

/**
 * Resolve one integer limit, falling back to the shipped default.
 *
 * @param value - configured value, or undefined.
 * @param fallback - default used when the value is absent.
 * @param label - field name for diagnostics.
 * @param allowZero - whether zero is accepted (redirect hops).
 * @param max - optional inclusive upper bound.
 * @returns the resolved limit.
 */
function resolveLimit(value, fallback, label, allowZero = false, max = Number.MAX_SAFE_INTEGER) {
  if (value === undefined) return fallback
  const minimum = allowZero ? 0 : 1
  if (!Number.isInteger(value) || value < minimum || value > max) {
    const bound =
      max === Number.MAX_SAFE_INTEGER
        ? allowZero
          ? 'a non-negative integer'
          : 'a positive integer'
        : `an integer in [${minimum}, ${max}]`
    throw new Error(`dsh-web-fetch-http-fakeip: ${label} must be ${bound}`)
  }
  return value
}

/**
 * Register the fake-ip-aware fetch provider.
 *
 * @param ctx - plugin context; must own the `web` service.
 * @param config - row config: `fakeIpRanges`, `id`, `debug`, and the shipped limit fields.
 * @returns nothing; the registration is disposed with the calling fiber.
 */
export async function apply(ctx, config) {
  const resolved = config ?? {}
  const rangeTexts = normalizeRangeConfig(resolved.fakeIpRanges)
  if (rangeTexts.length === 0) {
    throw new Error(
      'dsh-web-fetch-http-fakeip: fakeIpRanges is required — list the ranges your Clash DNS hands out ' +
        '(dns.fake-ip-range and dns.fake-ip-range6), e.g. ["198.18.0.1/16", "fdfe:dcba:9876::1/64"].',
    )
  }

  const peer = await importRuntimePackage(PEER_PACKAGE)
  const ipaddr = commonJsDefault(await importRuntimePackage(IPADDR_PACKAGE))
  const ranges = parseRanges(rangeTexts, ipaddr)

  const provider = new peer.HttpFetchProvider({
    maxResponseBytes: resolveLimit(resolved.maxResponseBytes, DEFAULT_LIMITS.maxResponseBytes, 'maxResponseBytes'),
    maxBodyChars: resolveLimit(resolved.maxBodyChars, DEFAULT_LIMITS.maxBodyChars, 'maxBodyChars'),
    timeoutMs: resolveLimit(resolved.timeoutMs, DEFAULT_LIMITS.timeoutMs, 'timeoutMs', false, MAX_NODE_TIMER_DELAY_MS),
    maxRedirects: resolveLimit(resolved.maxRedirects, DEFAULT_LIMITS.maxRedirects, 'maxRedirects', true),
    userAgent:
      typeof resolved.userAgent === 'string' && resolved.userAgent.trim() !== ''
        ? resolved.userAgent
        : peer.DEFAULT_USER_AGENT,
  })

  // The shipped class declares `id` as an own field, so assigning here replaces it.
  const configuredId = typeof resolved.id === 'string' ? resolved.id.trim() : ''
  provider.id = configuredId !== '' ? configuredId : 'http'

  const original = provider.resolveAddresses
  provider.resolveAddresses = createRangeResolver({
    original,
    ranges,
    ipaddr,
    debug: resolved.debug === true,
  })

  try {
    ctx.web.registerFetchProvider(provider)
  } catch (error) {
    if (error?.code === CODE_DUPLICATE_PROVIDER) {
      throw new Error(
        `dsh-web-fetch-http-fakeip: fetch provider id "${provider.id}" is already registered. ` +
          `Disable the shipped row (web-fetch-http), or set a distinct id and point the web row's ` +
          `fetchProvider at it. Original error: ${error.message}`,
      )
    }
    throw error
  }

  if (typeof ctx.logger?.info === 'function') {
    ctx.logger.info(`web_fetch accepts fake-ip ranges [${rangeTexts.join(', ')}] (id=${provider.id})`)
  }
}
