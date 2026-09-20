[app]

package.name = ctlx
package.domain = org.ctlx

app.title = 错题练习
package.version = 0.1

requirements = python3,kivy,pillow,requests

android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,CAMERA

source.dir = .
source.include_exts = py,png,jpg,json,txt

android.api = 33
android.ndk = 25b
android.sdk = 24

orientation = portrait
fullscreen = 0
log_level = 2
android.debug = 1
