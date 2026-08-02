package com.lf.systemtablet

import android.annotation.SuppressLint
import android.content.Context
import android.util.AttributeSet
import android.view.MotionEvent
import android.webkit.WebView

/**
 * WebView بحجم ثابت (100٪) — بدون تكبير مدمج حتى لا يكبّر التمرير/الضغط الجداول.
 * إعادة التكبير متاحة يدوياً عبر resetZoom إن لزم.
 */
class ZoomableWebView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : WebView(context, attrs) {

    var onZoomPanChanged: ((scale: Float, x: Float, y: Float) -> Unit)? = null

    init {
        @Suppress("DEPRECATION")
        settings.setSupportZoom(false)
        settings.builtInZoomControls = false
        settings.displayZoomControls = false
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = false
    }

    fun resetZoom() {
        @Suppress("DEPRECATION")
        settings.setSupportZoom(true)
        while (zoomOut()) {
            // keep zooming out
        }
        @Suppress("DEPRECATION")
        settings.setSupportZoom(false)
        scrollTo(0, 0)
    }

    fun currentScale(): Float = 1f

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        // لا تُبلّغ عن تغييرات تكبير — الحجم الطبيعي دائماً
        return super.onTouchEvent(event)
    }
}
