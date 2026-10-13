package com.powerk.app

/** Immutable request identity. Never publish a response belonging to another connection. */
@androidx.compose.runtime.Immutable
data class ServerConnection(val base: String, val token: String = "", val revision: Int = 0,
    val accountId: Long? = null, val legacy: Boolean = true) {
    fun isCurrent(current: ServerConnection): Boolean = this == current
    val authorized: Boolean get() = legacy || accountId != null
    override fun toString() = "ServerConnection(base=$base, revision=$revision, accountId=$accountId, legacy=$legacy)"
}

/** Pure guard used by UI loaders; callback receives the exact credentials captured at request start. */
internal suspend fun <T> connectionResult(connection: ServerConnection,
    current: () -> ServerConnection, fetch: suspend (ServerConnection) -> T): T? {
    val value = fetch(connection)
    return if (connection.isCurrent(current())) value else null
}
