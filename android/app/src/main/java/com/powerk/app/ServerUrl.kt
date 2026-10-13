package com.powerk.app

import java.net.URI
import java.net.InetAddress
import java.util.Locale

/** Set with powerk.serverUrl in android/local.properties. */
val DEFAULT_SERVER_URL: String = BuildConfig.SERVER_URL

data class ValidatedServerUrl(val base: String, val insecure: Boolean)

/** No DNS lookups: a public hostname resolving to a LAN IP must not bypass the HTTP rule. */
fun validateServerUrl(value: String): ValidatedServerUrl? = runCatching {
    val uri = URI(value.trim())
    val scheme = uri.scheme?.lowercase(Locale.ROOT)
    val host = uri.host?.lowercase(Locale.ROOT) ?: return null
    if (scheme !in listOf("https", "http") || uri.rawUserInfo != null || uri.rawQuery != null ||
        uri.rawFragment != null || uri.port !in -1..65535 || uri.port == 0 ||
        uri.rawPath.orEmpty().let { it.isNotEmpty() && it != "/" }) return null
    val lan = host == "localhost" || host.endsWith(".local") || privateLiteral(host)
    if (scheme == "http" && !lan) return null
    ValidatedServerUrl("$scheme://$host" + (if (uri.port == -1) "" else ":${uri.port}"), scheme == "http")
}.getOrNull()

private fun privateLiteral(host: String): Boolean {
    if (host.contains(':')) {
        val literal = host.removePrefix("[").removeSuffix("]")
        if (!literal.matches(Regex("[0-9a-fA-F:]+"))) return false
        val bytes = runCatching { InetAddress.getByName(literal).address }.getOrNull() ?: return false
        return bytes.size == 16 && (bytes.dropLast(1).all { it == 0.toByte() } && bytes.last() == 1.toByte() ||
            (bytes[0].toInt() and 0xfe) == 0xfc || (bytes[0].toInt() and 0xff) == 0xfe && (bytes[1].toInt() and 0xc0) == 0x80)
    }
    val parts = host.split('.')
    if (parts.size != 4 || parts.any { !it.matches(Regex("0|[1-9][0-9]{0,2}")) }) return false
    val ip = parts.map { it.toInt() }
    if (ip.any { it !in 0..255 }) return false
    return ip[0] == 10 || ip[0] == 127 || ip[0] == 192 && ip[1] == 168 ||
        ip[0] == 172 && ip[1] in 16..31 || ip[0] == 169 && ip[1] == 254
}
