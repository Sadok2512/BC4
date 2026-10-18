"""Admin-only template configuration with optimistic revision protection."""
import json
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_actor,require_role
from app.schemas.settings import Actor
from app.schemas.dict_templates import TemplateUpdate

router=APIRouter(prefix='/settings/dict/templates',tags=['dict-templates-admin'])

@router.put('/{category}',response_model=TemplateUpdate)
def update_template(category: str, body: TemplateUpdate, actor: Actor=Depends(get_actor),db: Session=Depends(get_db)):
    require_role(actor,'admin')
    row=db.execute(text('SELECT revision FROM dict_template WHERE category_id=:c FOR UPDATE'),{'c':category}).first()
    if row is None:raise HTTPException(404,'Catégorie introuvable')
    if row.revision!=body.revision:raise HTTPException(409,'Configuration modifiée ; rechargez avant de sauvegarder.')
    if any(not e.id.startswith(category+'-') for e in body.entries):raise HTTPException(422,'Les identifiants doivent commencer par la catégorie suivie de -.')
    entries=[e.model_dump() for e in body.entries]
    db.execute(text('UPDATE dict_template SET entries=CAST(:entries AS jsonb),revision=revision+1 WHERE category_id=:c'),{'c':category,'entries':json.dumps(entries)})
    # Preserve existing explicit assignments; newly configured full paths get this category.
    for e in entries:
        for ref in e['parameters']:
            db.execute(text('INSERT INTO dict_category_map(technology,path_prefix,category_id) VALUES (:technology,:param_key,:c) ON CONFLICT DO NOTHING'),dict(ref,c=category))
    db.commit()
    return TemplateUpdate(revision=body.revision+1,entries=body.entries)
