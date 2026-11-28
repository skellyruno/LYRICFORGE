"""Capture actual source-rendered UI and interactions; API fixtures are controlled.

This is not a native WebView2 or rendering test. Source is served locally
without remote resources, and only the application API is stubbed.
"""
import json, threading
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT=Path("creator-ui-evidence")
OUT.mkdir(exist_ok=True)
PROJECT="a"*32
def main():
    http=ThreadingHTTPServer(("127.0.0.1",0),SimpleHTTPRequestHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    url=f"http://127.0.0.1:{http.server_port}/static/index.html"
    report=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            for width,height in ((860,561),(390,780)):
                page=browser.new_page(viewport={"width":width,"height":height},device_scale_factor=1)
                requests=[]
                def reply(route):
                    req=route.request
                    path=req.url.split("/api/",1)[1].split("?",1)[0]
                    requests.append(path)
                    if path=="creator/writing-models":
                        result={"connected":True,"models":[{"name":"qwen2.5:1.5b","size_bytes":1000000000}]}
                    elif path=="creator/video-edit-instruction":
                        body=req.post_data_json
                        result={"settings":{**body["current"],"music":False},"changes":[{"setting":"music","before":True,"after":False}]}
                    elif path=="clips/capabilities":result={"ai_rerank":False,"ai_text":False,"watch":False}
                    elif path=="projects/"+PROJECT:result={"id":PROJECT,"title":"Example video","status":"ready","clip_suggestions":[]}
                    elif path=="presets":result={"presets":[]}
                    elif path in ("projects","makes"):result={"projects":[],"makes":[]}
                    else:result={}
                    route.fulfill(status=200,content_type="application/json",body=json.dumps(result))
                page.route("**/api/**",reply)
                page.goto(url,wait_until="domcontentloaded")
                page.wait_for_function("Boolean(window.SkellyUI && window.SkellyClips)")
                page.locator("#openResearchWelcome").evaluate("(e)=>e.click()")
                page.locator("#researchStudio").wait_for(state="visible")
                page.locator("#researchStudio details summary").click()
                page.locator("#researchModel option").nth(1).wait_for(state="attached")
                page.locator("#researchModel").select_option("qwen2.5:1.5b")
                assert page.locator("#researchModel").input_value()=="qwen2.5:1.5b"
                page.locator("#researchModel").select_option("")
                page.locator("#researchTopic").fill("How pitch correction works")
                box=page.locator("#researchRun").bounding_box()
                assert box and box["width"]>100
                page.screenshot(path=str(OUT/f"research-models-{width}.png"))
                page.locator("#researchHome").click()
                page.locator("#researchStudio").wait_for(state="hidden")
                page.evaluate("(id)=>window.SkellyClips.open(id,true)",PROJECT)
                page.locator("#clipReadyStep").wait_for(state="visible")
                page.locator("#aeMusic").check()
                page.locator(".video-instructions summary").click()
                page.locator("#aeInstruction").fill("music off")
                page.locator("#aeSuggest").click()
                page.locator("#aeApplySuggestion").wait_for(state="visible")
                assert page.locator("#aeMusic").is_checked()
                assert "music" in page.locator("#aeSuggested").inner_text()
                page.locator("#aeApplySuggestion").scroll_into_view_if_needed()
                page.screenshot(path=str(OUT/f"video-instructions-{width}.png"))
                page.locator("#aeApplySuggestion").click()
                assert not page.locator("#aeMusic").is_checked()
                assert not any(x.endswith("/autoedit") for x in requests)
                report.append({"width":width,"height":height,"research_create_button":box,"model_selection":True,"preview_apply":True,"no_automatic_render":True})
                page.close()
            browser.close()
    finally:
        http.shutdown();http.server_close()
        (OUT/"ui-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    assert len(report)==2

if __name__=="__main__":main()
