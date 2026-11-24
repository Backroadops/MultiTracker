# MultiTracker

Android real-time vehicle map built with Kotlin, Jetpack Compose and MapLibre; Python FastAPI backend.

This is an initial prototype, not a verified production release.

## Android
Open `android/` in Android Studio or run the GitHub Actions **Build Android APK** workflow. Set `API_URL` in `android/app/build.gradle.kts` to your deployed HTTPS backend before building.

## Backend
```sh
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

`GET /health` checks service status. `GET /vehicles` returns normalized positions. ADS-B uses adsb.lol with API limits; AIS and transit sources are planned, not yet live.

Never embed private API keys in the Android application. Map positions are informational, not for navigation or collision avoidance.
