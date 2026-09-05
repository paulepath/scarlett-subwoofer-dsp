import asyncio
import json
import yaml
import subprocess
import websockets
from aiohttp import web

CAMILLA_WS = "ws://127.0.0.1:1234"
CONFIG_BASS = "/home/pgj99/camilladsp/configs/subwoofer_active.yml"
CONFIG_FLAT = "/home/pgj99/camilladsp/configs/flat_bypass.yml"

def get_input_mode():
    try:
        out = subprocess.check_output(["amixer", "-c", "2", "cget", "numid=35"]).decode()
        for line in out.splitlines():
            if ": values=" in line:
                val = line.split(": values=")[1].strip()
                return "stereo" if val == "4" else "mono"
    except Exception:
        pass
    return "mono"

def set_hardware_input_mode(mode):
    try:
        if mode == "stereo":
            subprocess.run(["amixer", "-c", "2", "cset", "numid=34", "3"], check=True)
            subprocess.run(["amixer", "-c", "2", "cset", "numid=35", "4"], check=True)
        else:
            subprocess.run(["amixer", "-c", "2", "cset", "numid=34", "3"], check=True)
            subprocess.run(["amixer", "-c", "2", "cset", "numid=35", "3"], check=True)
        subprocess.run(["sudo", "alsactl", "store", "2"], check=False)
        return True
    except Exception as e:
        print("Error setting hardware input mode:", e)
        return False

async def get_cdsp_info():
    async with websockets.connect(CAMILLA_WS) as ws:
        await ws.send(json.dumps("GetConfigFilePath"))
        path_res = json.loads(await ws.recv())
        cur_path = path_res.get("GetConfigFilePath", {}).get("value", "")
        
        await ws.send(json.dumps("GetCaptureSignalPeak"))
        cap_res = json.loads(await ws.recv())
        cap_peak = cap_res.get("GetCaptureSignalPeak", {}).get("value", [-100, -100])
        
        await ws.send(json.dumps("GetPlaybackSignalPeak"))
        pb_res = json.loads(await ws.recv())
        pb_peak = pb_res.get("GetPlaybackSignalPeak", {}).get("value", [-100, -100])
        
        await ws.send(json.dumps("GetCaptureSignalRms"))
        cap_rms_res = json.loads(await ws.recv())
        cap_rms = cap_rms_res.get("GetCaptureSignalRms", {}).get("value", [-100, -100])
        
        await ws.send(json.dumps("GetPlaybackSignalRms"))
        pb_rms_res = json.loads(await ws.recv())
        pb_rms = pb_rms_res.get("GetPlaybackSignalRms", {}).get("value", [-100, -100])

        mode = "unfiltered" if "flat_bypass" in cur_path else "bass"
        
        freq = 120.0
        gain = 0.0
        try:
            with open(CONFIG_BASS, "r") as f:
                b_conf = yaml.safe_load(f)
                freq = b_conf.get("filters", {}).get("sub_lowpass", {}).get("parameters", {}).get("freq", 120.0)
                gain = b_conf.get("filters", {}).get("sub_gain", {}).get("parameters", {}).get("gain", 0.0)
        except Exception:
            pass
            
        in_mode = get_input_mode()
        
        return {
            "mode": mode,
            "freq": freq,
            "gain": gain,
            "input_mode": in_mode,
            "cap_peak": cap_peak,
            "pb_peak": pb_peak,
            "cap_rms": cap_rms,
            "pb_rms": pb_rms
        }

async def api_status(request):
    try:
        info = await get_cdsp_info()
        return web.json_response(info)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_set_mode(request):
    try:
        data = await request.json()
        target_mode = data.get("mode")
        target_path = CONFIG_FLAT if target_mode == "unfiltered" else CONFIG_BASS
        
        async with websockets.connect(CAMILLA_WS) as ws:
            await ws.send(json.dumps({"SetConfigFilePath": target_path}))
            await ws.recv()
            await ws.send(json.dumps("Reload"))
            await ws.recv()
            
        return web.json_response({"result": "ok", "mode": target_mode})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_set_filter(request):
    try:
        data = await request.json()
        freq = float(data.get("freq", 120.0))
        gain = float(data.get("gain", 0.0))
        
        with open(CONFIG_BASS, "r") as f:
            b_conf = yaml.safe_load(f)
        
        b_conf["filters"]["sub_lowpass"]["parameters"]["freq"] = freq
        b_conf["filters"]["sub_gain"]["parameters"]["gain"] = gain
        
        with open(CONFIG_BASS, "w") as f:
            yaml.dump(b_conf, f)
            
        async with websockets.connect(CAMILLA_WS) as ws:
            await ws.send(json.dumps("GetConfigFilePath"))
            path_res = json.loads(await ws.recv())
            cur_path = path_res.get("GetConfigFilePath", {}).get("value", "")
            if "subwoofer_active" in cur_path:
                await ws.send(json.dumps("Reload"))
                await ws.recv()
                
        return web.json_response({"result": "ok", "freq": freq, "gain": gain})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_set_input_mode(request):
    try:
        data = await request.json()
        target_mode = data.get("input_mode", "mono")
        set_hardware_input_mode(target_mode)
        return web.json_response({"result": "ok", "input_mode": target_mode})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def index(request):
    return web.FileResponse("/home/pgj99/camilladsp/index.html")

app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/favicon.ico", lambda r: web.Response(status=204))
app.router.add_get("/api/status", api_status)
app.router.add_post("/api/mode", api_set_mode)
app.router.add_post("/api/filter", api_set_filter)
app.router.add_post("/api/input_mode", api_set_input_mode)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=5050)
