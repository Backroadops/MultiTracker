package com.backroadops.multitracker

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.maplibre.android.MapLibre
import org.maplibre.android.annotations.MarkerOptions
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.MapView

class MainActivity : ComponentActivity() {
    private val client = OkHttpClient()
    private var mapView: MapView? = null
    private var map: org.maplibre.android.maps.MapLibreMap? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        MapLibre.getInstance(this)
        setContent {
            var status by remember { mutableStateOf("Waiting for backend") }
            var vehicles by remember { mutableStateOf(JSONArray()) }
            var enabled by remember { mutableStateOf(setOf("aircraft", "helicopter", "ship", "train", "bus", "other")) }
            var mapReady by remember { mutableIntStateOf(0) }
            val requestLocation = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
                if (granted.values.any { it }) centerOnLocation()
            }
            LaunchedEffect(Unit) {
                while (true) {
                    try {
                        val result = withContext(Dispatchers.IO) {
                            val center = map?.cameraPosition?.target ?: LatLng(59.33, 18.06)
                            val url = BuildConfig.API_URL.trimEnd('/') + "/vehicles?lat=" + center.latitude + "&lon=" + center.longitude
                            client.newCall(Request.Builder().url(url).build()).execute().use { response ->
                                if (!response.isSuccessful) error("HTTP " + response.code)
                                JSONArray(response.body?.string() ?: "[]")
                            }
                        }
                        vehicles = result
                        status = "${result.length()} vehicles"
                    } catch (e: Exception) {
                        status = "Backend offline: ${e.message ?: "connection error"}"
                    }
                    delay(60000)
                }
            }
            LaunchedEffect(vehicles, enabled, mapReady) {
                map?.let { m ->
                    m.clear()
                    for (i in 0 until vehicles.length()) {
                        val v = vehicles.optJSONObject(i) ?: continue
                        if (v.optString("type") !in enabled) continue
                        m.addMarker(MarkerOptions()
                            .position(LatLng(v.optDouble("latitude"), v.optDouble("longitude")))
                            .title(v.optString("label", v.optString("id")))
                            .snippet(v.optString("type") + " · " + v.optDouble("speed_kmh") + " km/h"))
                    }
                }
            }
            Column {
                Text("MultiTracker", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(12.dp))
                Text(status, modifier = Modifier.padding(horizontal = 12.dp))
                Row {
                    Button(onClick = {
                        if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                            ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                            centerOnLocation()
                        } else requestLocation.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
                    }) { Text("My location") }
                    Button(onClick = { map?.animateCamera(CameraUpdateFactory.newLatLngZoom(LatLng(59.33, 18.06), 6.0)) }) { Text("Sweden") }
                }
                Row {
                    listOf("aircraft", "helicopter", "ship", "train", "bus").forEach { kind ->
                        FilterChip(
                            selected = kind in enabled,
                            onClick = { enabled = if (kind in enabled) enabled - kind else enabled + kind },
                            label = { Text(kind.take(3)) }
                        )
                    }
                }
                AndroidView(
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    factory = { context ->
                        MapView(context).also { view ->
                            mapView = view
                            view.onCreate(savedInstanceState)
                            view.onStart()
                            view.onResume()
                            view.getMapAsync { m ->
                                map = m
                                m.setStyle("https://tiles.openfreemap.org/styles/liberty") {
                                    m.moveCamera(CameraUpdateFactory.newLatLngZoom(LatLng(59.33, 18.06), 6.0))
                                    mapReady++
                                }
                            }
                        }
                    }
                )
            }
        }
    }

    private fun centerOnLocation() {
        val lm = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        try {
            val loc = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
            loc?.let { map?.animateCamera(CameraUpdateFactory.newLatLngZoom(LatLng(it.latitude, it.longitude), 10.0)) }
        } catch (_: SecurityException) {}
    }
    override fun onStart() { super.onStart(); mapView?.onStart() }
    override fun onResume() { super.onResume(); mapView?.onResume() }
    override fun onPause() { mapView?.onPause(); super.onPause() }
    override fun onStop() { mapView?.onStop(); super.onStop() }
    override fun onLowMemory() { super.onLowMemory(); mapView?.onLowMemory() }
    override fun onDestroy() { mapView?.onDestroy(); super.onDestroy() }
}
