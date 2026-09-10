package com.connectedgallery.domain

class PhotoRefreshFailure(val userMessage: String, cause: Throwable? = null) : Exception(userMessage, cause)
