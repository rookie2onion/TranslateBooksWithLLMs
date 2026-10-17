/**
 * Localized messages for the stable error codes of the online PDF path.
 *
 * The server never sends a provider URL or credential here: just a stable
 * technical code (plus optional limit values). This module maps the known codes
 * to translation keys, so every label follows a language switch with no reload
 * (`t()` is called at render time, never cached at module load).
 */

import { t } from '../i18n/i18n.js';

// Codes emitted by src/core/mineru/errors.py (the "mineru_" prefix is stripped
// to form the translation key). Kept as tokens, never shown to the user.
const KNOWN_CODES = new Set([
    'mineru_authorization_required',
    'mineru_token_missing',
    'mineru_pdf_unreadable',
    'mineru_pdf_encrypted',
    'mineru_page_limit',
    'mineru_byte_limit',
    'mineru_state_unavailable',
    'mineru_continuation_unavailable',
    'mineru_submission_unknown',
    'mineru_upload_failed',
    'mineru_recognition_failed',
    'mineru_recognition_timeout',
    'mineru_recognition_interrupted',
    'mineru_network_error',
    'mineru_response_invalid',
    'mineru_provider_rejected',
    'mineru_result_invalid',
    'mineru_unsupported_content',
    'mineru_output_invalid',
]);

const DEFAULT_MAX_PAGES = 200;
const DEFAULT_MAX_BYTES = 200000000;

/**
 * Resolve a server error code to a localized message.
 * @param {string|null|undefined} code - Stable server error code
 * @param {Object} [details] - Server payload; only `limits` is read
 * @returns {string|null} Localized message, or null when the code is unknown
 */
export function resolveMineruError(code, details) {
    if (!code || typeof code !== 'string' || !KNOWN_CODES.has(code)) return null;

    const limits = (details && details.limits) || {};
    const params = {};
    if (code === 'mineru_page_limit') {
        params.max = limits.max_pages || DEFAULT_MAX_PAGES;
    } else if (code === 'mineru_byte_limit') {
        params.max = Math.round((limits.max_bytes || DEFAULT_MAX_BYTES) / 1000000);
    }

    const key = `translation:mineru_error_${code.slice('mineru_'.length)}`;
    return Object.keys(params).length ? t(key, params) : t(key);
}
