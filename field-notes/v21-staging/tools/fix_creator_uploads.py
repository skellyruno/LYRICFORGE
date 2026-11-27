from pathlib import Path
import sys

def once(s,a,b):
    if s.count(a)!=1:raise ValueError('Unexpected source anchor: '+a[:100])
    return s.replace(a,b,1)

def apply(root):
    p=Path(root)/'server.py';s=p.read_text(encoding='utf-8')
    s=once(s,"        script=(creator.validate_script(body.chapters,body.production_mode) if body.chapters else creator.chapters_from_text(body.script_text)","        if len(files)>40 or len(body.visual_roles)>len(files): raise ValueError('At most 40 visual uploads; metadata must match files')\n        from studio_media_layers import bind_uploads\n        suffixes=[Path(f.filename or '').suffix.lower() for f in files]\n        preflight=bind_uploads(body.chapters,suffixes) if body.chapters else []\n        script=(creator.validate_script(preflight,body.production_mode) if body.chapters else creator.chapters_from_text(body.script_text)")
    s=once(s,"'creator_script':script,'creator_brief':body.brief","'creator_script':[] if body.chapters else script,'creator_brief':body.brief")
    s=once(s,"        for i,file in enumerate(files):\n            meta=body.visual_roles[i]", "        actual_ids=[]\n        for i,file in enumerate(files):\n            meta=body.visual_roles[i]")
    s=once(s,"            await add_director_asset(project_id,file,desc,role,group,order,meta.get('focus_x'),meta.get('focus_y'),meta.get('trim_start',0),meta.get('trim_end',0))\n        job_id=register_job(project_id,'creator',settings)","            added=await add_director_asset(project_id,file,desc,role,group,order,meta.get('focus_x'),meta.get('focus_y'),meta.get('trim_start',0),meta.get('trim_end',0))\n            actual_ids.append(added['asset_id'])\n        if body.chapters:\n            script=creator.validate_script(bind_uploads(body.chapters,suffixes,actual_ids),body.production_mode)\n            data['creator_script']=script\n            save_project(p,data)\n        job_id=register_job(project_id,'creator',settings)")
    s=once(s,"    except Exception:\n        # Only remove the newly allocated, unpublished project, never existing user files.\n        shutil.rmtree(p,ignore_errors=True);raise\n    executor.submit(run_creator", "    except (ValueError,TypeError) as exc:\n        shutil.rmtree(p,ignore_errors=True)\n        raise HTTPException(400,str(exc)[:500]) from exc\n    except Exception:\n        # Only remove the newly allocated, unpublished project, never existing user files.\n        shutil.rmtree(p,ignore_errors=True);raise\n    executor.submit(run_creator")
    s=once(s,"return {'assets':director.assets_for(folder,include_disabled=True),'duplicate':True}","return {'assets':director.assets_for(folder,include_disabled=True),'duplicate':True,'asset_id':key}")
    s=once(s,"    return {\"assets\": director.assets_for(folder,include_disabled=True)}\n\n\ndef prepare_director", "    return {\"assets\": director.assets_for(folder,include_disabled=True),'asset_id':name}\n\n\ndef prepare_director")
    s=once(s,"            row.update(chapter_title=cue.get('chapter_title',''),visual_hint=cue.get('visual_hint',''),source_url=cue.get('source_url',''))", "            row.update(chapter_title=cue.get('chapter_title',''),visual_hint=cue.get('visual_hint',''),source_url=cue.get('source_url',''))\n            if cue.get('graphic'):row['graphic']=cue['graphic']")
    compile(s,str(p),'exec');p.write_text(s,encoding='utf-8')

if __name__=='__main__':apply(sys.argv[1])
