package com.connectedgallery.data

import org.junit.Assert.*
import org.junit.Test

class ServerEndpointTest {
 private val key="a".repeat(43)
 @Test fun acceptsHttpsAndFutureBackendPrefix() {
  val value=ServerEndpoint.validated(" https://gallery.example.com/api/ "," $key ")
  assertEquals("https://gallery.example.com/api",value.url)
  assertEquals(key,value.token)
 }
 @Test fun rejectsInsecureOrAmbiguousAddresses() {
  listOf("http://192.168.0.1:8765", "http://gallery.example.com", "https://user:pass@example.com",
   "https://example.com?token=secret", "https://example.com/#fragment", "bad").forEach { url ->
   assertThrows(IllegalArgumentException::class.java) {ServerEndpoint.validated(url,key)}
  }
  assertThrows(IllegalArgumentException::class.java) {ServerEndpoint.validated("https://example.com","short")}
 }
 @Test fun loopbackRemainsAvailableForExplicitDevelopment() {
  assertEquals("http://127.0.0.1:8765",ServerEndpoint.validated("http://127.0.0.1:8765",key).url)
 }
}
