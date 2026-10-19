"""Build reviewable v2.2 CONFIGURATION from observed paths; never infer from display names.
Run from bc4-back. Exact, contextual ASN.1 prefixes only. Unmatched paths remain UNRESOLVED.
"""
import csv, hashlib, json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "audit/dict-v2.2"
OUTPUT = ROOT / "app/dict/config/categories_v22.json"

# Taxonomy transcribed from the user's validated inline specification.
TAXONOMY = [
 ("phy", "PHY", [("carrier","Porteuse & bande passante"),("csi","CSI & rapport canal"),("reference","Signaux de référence"),("prach","Accès aléatoire PRACH")]),
 ("power-control","Power control",[("common","Commun (SIB2)"),("dedicated","Dédié"),("random-access","Accès aléatoire"),("nr","NR")]),
 ("mobility","Mobility (connected)",[("intra","Événements intra-fréquence"),("inter","Événements inter-fréquence"),("inter-rat","Inter-RAT / NR"),("objects","Objets de mesure"),("quantities","Quantités & filtrage"),("handover","Exécution du handover"),("gaps","Gaps de mesure")]),
 ("layering-idle","Layering strategy — Idle",[("access","Accès cellule (SIB1)"),("serving","Resélection serving (SIB3)"),("intra","Intra-fréquence (SIB4)"),("inter","Inter-fréquence (SIB5)"),("inter-rat","Inter-RAT (SIB6/7)"),("release","Orientation au release")]),
 ("layering-connected","Layering strategy — Connected",[("layers","Couches mesurées"),("switch","Logique de bascule"),("ca","Agrégation de porteuses"),("endc","EN-DC")]),
 ("mimo-ca","MIMO / CA",[("antennas","Antennes & rangs"),("scell","SCell"),("nr","NR MIMO")]),
 ("mac","MAC",[("harq","HARQ"),("bsr-phr","BSR / PHR"),("sr","Scheduling request"),("timing","Alignement temporel"),("random-access","Accès aléatoire MAC")]),
 ("rlc-pdcp","RLC / PDCP",[("am-dl","RLC AM — DL"),("am-ul","RLC AM — UL"),("um","RLC UM"),("pdcp","PDCP"),("nr","NR")]),
 ("drx","DRX",[("long","Cycle long"),("short","Cycle court"),("timers","Timers"),("nr","NR")]),
 ("timers-rlf","Timers & RLF",[("connection","Connexion"),("rlf","RLF"),("nr-scg","NR SCG")]),
 ("access-barring","Accès & barring",[("barring","Barring"),("common-timers","Timers UE communs")]),
 ("security","Sécurité",[("algorithms","Algorithmes")]),
]
NEW_SUBCATEGORIES = {
 'access-barring': [('causes','Causes de procédure')],
 'rlc-pdcp': [('bearers','Bearers & mode RLC')],
 'mobility': [('reports','Configuration des rapports'),('speed','État de mobilité (speed scaling)')],
 'mac': [('logical','Canaux logiques'),('sps','Scheduling semi-persistant')],
 'timers-rlf': [('reports','Rapports RLF & RACH')],
 'layering-connected': [('bands','Bandes demandées au terminal')],
 'layering-idle': [('paging','Paging & information système')],
}
for cid, _, subs in TAXONOMY:
 subs.extend(NEW_SUBCATEGORIES.get(cid, []))
categories=[];subcategories=[]
for position,(cid,label,subs) in enumerate(TAXONOMY,1):
 categories.append(dict(id=cid,label=label,position=position,tech="BOTH"))
 for pos,(code,label) in enumerate(subs,1):
  subcategories.append(dict(id=cid+"."+code,category_id=cid,code=code,label=label,position=pos))
categories.append(dict(id="autres",label="Autres",position=99,tech="BOTH"))
# No artificial 'Other' subcategory. No assignment to Autres until explicit review.
def normalize(path):
 return "/".join("[*]" if re.fullmatch(r"\[\d+\]",segment) else segment for segment in path.split("/"))
def starts(path,prefix):
 return path==prefix or path.startswith(prefix+"/")
rules=[]
def rule(prefix,subcategory,note,tech="LTE",discriminator=None):
 rules.append(dict(technology=tech,path_prefix=prefix,subcategory_id=subcategory,
                   category_id=subcategory.split(".")[0],discriminator=discriminator or {},note=note))
SPEC="Spécification utilisateur dict_categories (inline), contexte ASN.1 vérifié dans paths.csv"
def add(prefix,sub):rule(prefix,sub,SPEC)
add("dl-Bandwidth","phy.carrier")
add("phich-Config","phy.carrier")
RECONF="rrcConnectionReconfiguration/rrcConnectionReconfiguration-r8"
SETUP="rrcConnectionSetup/rrcConnectionSetup-r8"
SI="systemInformation/systemInformation-r8/sib-TypeAndInfo/[*]"
SIB1="systemInformationBlockType1"
# Physical common context appears in SIB2 and in handover configuration.
common_roots=[SI+"/sib2/radioResourceConfigCommon",RECONF+"/mobilityControlInfo/radioResourceConfigCommon"]
for base in common_roots:
 for field,sub in {
  "antennaInfoCommon":"mimo-ca.antennas","p-Max":"power-control.common",
  "phich-Config":"phy.carrier","prach-Config":"phy.prach",
  "pucch-ConfigCommon":"phy.reference","pusch-ConfigCommon":"phy.reference",
  "pusch-ConfigCommon-v1270":"phy.reference","pdsch-ConfigCommon":"phy.reference",
  "soundingRS-UL-ConfigCommon":"phy.reference","ul-CyclicPrefixLength":"phy.carrier",
  "uplinkPowerControlCommon":"power-control.common",
  "uplinkPowerControlCommon-v1020":"power-control.common",
  "rach-ConfigCommon/maxHARQ-Msg3Tx":"mac.harq",
  "rach-ConfigCommon/powerRampingParameters":"power-control.random-access",
  "rach-ConfigCommon/preambleInfo/numberOfRA-Preambles":"phy.prach",
  "rach-ConfigCommon/preambleInfo/preamblesGroupAConfig":"phy.prach",
  "rach-ConfigCommon/ra-SupervisionInfo/mac-ContentionResolutionTimer":"mac.random-access",
  "rach-ConfigCommon/ra-SupervisionInfo/preambleTransMax":"phy.prach",
  # ra-ResponseWindowSize intentionally unresolved: appears in two spec categories.
 }.items():add(base+"/"+field,sub)
for base in [RECONF+"/radioResourceConfigDedicated",SETUP+"/radioResourceConfigDedicated"]:
 phy=base+"/physicalConfigDedicated"
 for field,sub in {
  "antennaInfo":"mimo-ca.antennas","antennaInfo-r10":"mimo-ca.antennas",
  "cqi-ReportConfig":"phy.csi","cqi-ReportConfig-r10":"phy.csi",
  "cqi-ReportConfigPCell-v1250":"phy.csi","csi-RS-Config-r10":"phy.csi",
  "pdsch-ConfigDedicated":"phy.reference","pdsch-ConfigDedicated-v1430":"phy.reference",
  "pucch-ConfigDedicated":"phy.reference","pucch-ConfigDedicated-v1020":"phy.reference",
  "pusch-ConfigDedicated":"phy.reference","pusch-ConfigDedicated-v1430":"phy.reference",
  "schedulingRequestConfig":"mac.sr","soundingRS-UL-ConfigDedicated":"phy.reference",
  "uplinkPowerControlDedicated":"power-control.dedicated",
  "tpc-PDCCH-ConfigPUCCH":"power-control.dedicated",
  "tpc-PDCCH-ConfigPUSCH":"power-control.dedicated",
 }.items():add(phy+"/"+field,sub)
 mac=base+"/mac-MainConfig/explicitValue"
 for field,sub in {
  "phr-Config":"mac.bsr-phr","dualConnectivityPHR":"mac.bsr-phr",
  "mac-MainConfig-v1020/extendedBSR-Sizes-r10":"mac.bsr-phr",
  "mac-MainConfig-v1020/extendedPHR-r10":"mac.bsr-phr",
  "sr-ProhibitTimer-r9":"mac.sr","timeAlignmentTimerDedicated":"mac.timing",
  "ul-SCH-Config/maxHARQ-Tx":"mac.harq","ul-SCH-Config/ttiBundling":"mac.harq",
  "ul-SCH-Config/periodicBSR-Timer":"mac.bsr-phr",
  "ul-SCH-Config/retxBSR-Timer":"mac.bsr-phr",
  "drx-Config":"drx.long",
  "drx-Config/setup/shortDRX":"drx.short",
  "drx-Config/setup/onDurationTimer":"drx.timers",
  "drx-Config/setup/drx-InactivityTimer":"drx.timers",
  "drx-Config/setup/drx-RetransmissionTimer":"drx.timers",
 }.items():add(mac+"/"+field,sub)
 for bearer,choice in [("drb-ToAddModList",""),("srb-ToAddModList","/explicitValue")]:
  b=base+"/"+bearer+"/[*]"
  # logicalChannelConfig not assigned: MAC taxonomy has no logical-channel subcategory.
  add(b+"/pdcp-Config","rlc-pdcp.pdcp")
  for mode,sub in [("/am/dl-AM-RLC","rlc-pdcp.am-dl"),("/am/ul-AM-RLC","rlc-pdcp.am-ul"),("/um-Bi-Directional","rlc-pdcp.um"),("/um-Uni-Directional-DL","rlc-pdcp.um"),("/um-Uni-Directional-UL","rlc-pdcp.um")]:
   add(b+"/rlc-Config"+choice+mode,sub)
 # dedicated t301 must override the broader RLF context.
 add(base+"/rlf-TimersAndConstants-r9","timers-rlf.rlf")
 add(base+"/rlf-TimersAndConstants-r9/setup/t301-r9","timers-rlf.connection")
meas=RECONF+"/measConfig"
add(meas+"/measGapConfig","mobility.gaps")
add(meas+"/mgta-r15","mobility.gaps")
add(meas+"/quantityConfig","mobility.quantities")
add(meas+"/s-Measure","mobility.quantities")
add(meas+"/measObjectToRemoveList","mobility.objects")
add(meas+"/measIdToRemoveList","layering-connected.switch")
obj=meas+"/measObjectToAddModList/[*]/measObject"
add(obj,"mobility.objects")
for objtype,freq in [("measObjectEUTRA","carrierFreq"),("measObjectUTRA","carrierFreq"),("measObjectNR-r15","carrierFreq-r15")]:
 add(obj+"/"+objtype+"/"+freq,"layering-connected.layers")
report=meas+"/reportConfigToAddModList/[*]/reportConfig"
for kind in ["reportConfigEUTRA","reportConfigInterRAT"]:
 base=report+"/"+kind
 for field in ["maxReportCells","reportAddNeighMeas-r10","reportAmount","reportInterval","reportQuantity",
               "triggerQuantity","reportQuantityUTRA-FDD-r10","reportQuantityCellNR-r15",
               "reportQuantityRS-IndexNR-r15","reportRS-IndexResultsNR","maxReportRS-Index-r15"]:
  add(base+"/"+field,"mobility.quantities")
 for event in ["eventA1","eventA2","eventA4","eventA5"]:
  add(base+"/triggerType/event/eventId/"+event,"mobility.inter")
 for event in ["eventA3","eventA6-r10"]:
  add(base+"/triggerType/event/eventId/"+event,"mobility.intra")
 for event in ["eventB1","eventB2","eventB1-NR-r15","eventB2-NR-r15"]:
  add(base+"/triggerType/event/eventId/"+event,"mobility.inter-rat")
 # event-scoped siblings hysteresis/timeToTrigger need a discriminator.
 # Filled below from actual discriminators ONLY. No inference from nearby indexed rows.
for field,sub in {
 "carrierBandwidth":"phy.carrier","carrierFreq":"phy.carrier",
 "rach-ConfigDedicated":"mobility.handover","t304":"mobility.handover","targetPhysCellId":"mobility.handover",
}.items():add(RECONF+"/mobilityControlInfo/"+field,sub)
add(RECONF+"/securityConfigHO/handoverType/intraLTE","security.algorithms")
add("securityModeCommand/securityModeCommand-r8/securityConfigSMC/securityAlgorithmConfig","security.algorithms")
release="rrcConnectionRelease/rrcConnectionRelease-r8"
add(release+"/idleModeMobilityControlInfo","layering-idle.release")
add(release+"/redirectedCarrierInfo","layering-idle.release")
# Broadcast contexts: do not assign the whole SIB2 to an arbitrary category.
for field,sub in {
 "freqInfo":"phy.carrier","timeAlignmentTimerCommon":"mac.timing",
 "ac-BarringInfo":"access-barring.barring","ac-BarringSkipForMMTELVideo-r12":"access-barring.barring",
 "ac-BarringSkipForMMTELVoice-r12":"access-barring.barring","ac-BarringSkipForSMS-r12":"access-barring.barring",
}.items():add(SI+"/sib2/"+field,sub)
for field in ["t300","t301","t302","t303","t305","t306"]:
 add(SI+"/sib2/ue-TimersAndConstants/"+field,"timers-rlf.connection")
for field in ["t310","n310","n311","t311"]:
 add(SI+"/sib2/ue-TimersAndConstants/"+field,"timers-rlf.rlf")
add(SI+"/sib3","layering-idle.serving")
add(SI+"/sib4","layering-idle.intra")
add(SI+"/sib5","layering-idle.inter")
add(SI+"/sib6","layering-idle.inter-rat")
add(SI+"/sib7","layering-idle.inter-rat")
add(SI+"/sib24-v1530","layering-idle.inter-rat")
# Explicit SIB1 paths from the cell-access group, no broad identity inference.
for field in ["cellSelectionInfo","cellAccessRelatedInfo/cellBarred",
 "cellAccessRelatedInfo/csg-Indication","cellAccessRelatedInfo/intraFreqReselection",
 "cellAccessRelatedInfo/plmn-IdentityList/[*]/cellReservedForOperatorUse",
 "freqBandIndicator","p-Max","si-WindowLength"]:
 add(SIB1+"/"+field,"layering-idle.access")
# NR MIB context; SFN and the independent FreqBandList IE await review.
for field,sub in {
 "cellBarred":"layering-idle.access","intraFreqReselection":"layering-idle.access",
 "dmrs-TypeA-Position":"phy.reference","ssb-SubcarrierOffset":"phy.carrier",
 "subCarrierSpacingCommon":"phy.carrier",
}.items():rule("mib/"+field,sub,SPEC,tech="NR")

rows=list(csv.DictReader((AUDIT/"path-populations.csv").open()))
for r in rows:
 r["normalized_path"]=normalize(r["path"])
 r["disc"]=json.loads(r["discriminators"]) if r["discriminators"] else {}
# Do not invent event discriminator field names; inspect actual observed dictionaries.
event_scope={
 "A1":"mobility.inter","A2":"mobility.inter","A4":"mobility.inter","A5":"mobility.inter",
 "A3":"mobility.intra","A6":"mobility.intra",
 "B1":"mobility.inter-rat","B2":"mobility.inter-rat"
}
seen=set()
for r in rows:
 if r["origin"]!="network_config":continue
 for kind in ["reportConfigEUTRA","reportConfigInterRAT"]:
  base=report+"/"+kind+"/triggerType/event"
  if r["normalized_path"] not in [base+"/timeToTrigger",base+"/hysteresis",base+"/eventId"]:continue
  for key,val in r["disc"].items():
   if key=="event" and val in event_scope:
    ident=(r["system"],r["normalized_path"],val)
    if ident not in seen:
     seen.add(ident)
     rule(r["normalized_path"],event_scope[val],SPEC+" ; event enregistré dans les discriminants",r["system"],{key:val})
# Exact observed paths approved by the user, Q01-Q16 (2026-10-19).
answers=json.loads((AUDIT/'classification-answers.json').read_text())
for answer in answers:
 if answer['subcategory_id']:
  rule(answer['path'],answer['subcategory_id'],'Décision utilisateur '+answer['question_id'],answer['technology'],answer['discriminator'])
rows=[r for r in rows if not any(a['exclusion'] and a['technology']==r['system'] and a['path']==r['normalized_path'] for a in answers)]
for r in rows:
 if '/logicalChannelConfig/' in r['normalized_path'] and r['normalized_path'].endswith('/logicalChannelGroup'):
  rule(r['normalized_path'],'mac.logical','Correction utilisateur Q05 : LCG du BSR',r['system'])
def matching(r):
 matches=[rule for rule in rules if rule["technology"]==r["system"] and starts(r["normalized_path"],rule["path_prefix"])
          and all(r["disc"].get(k)==v for k,v in rule["discriminator"].items())]
 if not matches:return None
 matches.sort(key=lambda x:(len(x["path_prefix"].split("/")),len(x["discriminator"])),reverse=True)
 best=matches[0]
 equals=[x for x in matches if (len(x["path_prefix"].split("/")),len(x["discriminator"]))==(len(best["path_prefix"].split("/")),len(best["discriminator"]))]
 assert len({x["subcategory_id"] for x in equals})==1,equals
 return best
def question(r):
 p=r["normalized_path"]
 if "/ra-ResponseWindowSize" in p:return "La spec place ra-ResponseWindowSize dans PHY/PRACH et MAC/Accès aléatoire : quelle affectation unique retenir ?"
 if "/logicalChannelConfig/" in p:return "Configuration logique MAC (priorité/PBR/bucket/SR-mask) : aucune sous-catégorie MAC correspondante dans la spec. Quelle sous-catégorie retenir ou ajouter ?"
 if "/sps-Config/" in p:return "SPS : quelle sous-catégorie MAC de la spec, qui ne contient pas Scheduling semi-persistant ?"
 if p.endswith("/rlc-Config"):return "Feuille CHOICE du mode RLC : AM couvre DL et UL ; quelle sous-catégorie unique pour la valeur du mode elle-même ?"
 if "/rlc-Config-v1510/" in p or "/drb-ToReleaseList" in p:return "Commande RLC/bearer sans direction AM/UM établie : quelle sous-catégorie de RLC/PDCP ?"
 if "/speedStatePars" in p:return "État de mobilité et facteur de temps communs à plusieurs événements : quelle sous-catégorie Mobility sans inventer intra/inter ?"
 if "/triggerType" in p or "/reportConfig" in p:return "Configuration de rapport/CHOICE : événement non prouvé par un discriminant applicable ou sous-catégorie commune absente. Quelle sous-catégorie ?"
 if "/bcch-Config/" in p or "/pcch-Config/" in p or "schedulingInfo" in p or p.endswith("systemInfoUnchanged-BR-r15") or p.endswith("/systemInfoValueTag") or "sib-MappingInfo" in p:return "Planification SI/paging : aucune sous-catégorie explicite dans la spec. Accès cellule, DRX, ou nouvelle sous-catégorie ?"
 if p.endswith("systemFrameNumber"):return "SFN BIT STRING conservé conformément à la règle c : quelle catégorie/sous-catégorie pour ce compteur de trame ?"
 if "/cellIdentity" in p or "/trackingAreaCode" in p or "/plmn-Identity/" in p:return "is_identifier=false en base : conserver selon a+b. Quelle sous-catégorie pour cet identifiant réseau public (pas d'exclusion déduite du nom) ?"
 if "/bandInformation" in p:return "FreqBandList IE stocké sous network_config : ne pas réassigner l'origine. Quelle catégorie/sous-catégorie pour ces bandes d'un IE autonome ?"
 if "/pdcch-ConfigSIB1/" in p:return "CORESET0/SearchSpace0 du MIB NR : PHY/Porteuse ou PHY/Signaux de référence ? La spec ne tranche pas."
 if p.endswith("/establishmentCause") or p.endswith("/releaseCause"):return "Cause de procédure (hors timers et barring) : quelle catégorie/sous-catégorie ?"
 if "ueInformationRequest" in p:return "Demande de rapport RACH/RLF (commande, pas mesure rapportée) : quelle catégorie/sous-catégorie ?"
 if p.endswith("/additionalSpectrumEmission"):return "Émission additionnelle dans mobilityControlInfo : PHY/Porteuse ou Mobility/Exécution du handover ?"
 if "voiceServiceCauseIndication" in p or "upperLayerIndication" in p:return "Indication de service/couche supérieure : quelle catégorie/sous-catégorie de la spec ?"
 return "Chemin observé sans règle exacte justifiée par la spec : préciser catégorie et sous-catégorie."
# Store an exact normalized leaf prefix for each classified population, not a fuzzy rule.
mapped={};unmapped={};coverage=[]
for r in rows:
 m=matching(r) if r["origin"]=="network_config" else None
 state="PRESERVED_ROOT" if r["origin"]!="network_config" else "MAPPED" if m else "UNRESOLVED"
 coverage.append(dict(system=r["system"],origin=r["origin"],message=r["message"],path=r["path"],param_key=r["param_key"],
                      discriminator=r["discriminators"],n_occurrences=r["n_occurrences"],state=state,
                      subcategory_id=m["subcategory_id"] if m else ""))
 if state=="MAPPED":
  key=(r["system"],r["normalized_path"],json.dumps(m["discriminator"],sort_keys=True))
  item=dict(m,path_prefix=r["normalized_path"],note=m["note"]+" ; préfixe de contexte: "+m["path_prefix"])
  if key in mapped:assert mapped[key]["subcategory_id"]==item["subcategory_id"]
  mapped[key]=item
 elif state=="UNRESOLVED":
  key=(r["system"],r["message"],r["normalized_path"],json.dumps(r["disc"],sort_keys=True))
  item=unmapped.setdefault(key,dict(technology=r["system"],message=r["message"],path=r["normalized_path"],param_key=r["param_key"],
                                   discriminator=json.dumps(r["disc"],ensure_ascii=False,sort_keys=True),
                                   n_occurrences=0,question=question(r),category_id="",subcategory_id=""))
  item["n_occurrences"]+=int(r["n_occurrences"])
def write_csv(name,rows,fields=None):
 with (AUDIT/name).open("w",newline="") as f:
  w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)
question_ids={q:f"Q{i:02d}" for i,q in enumerate(sorted({r["question"] for r in unmapped.values()}),1)}
for item in unmapped.values():
 item["question_id"]=question_ids[item["question"]]
with (AUDIT/"questions.txt").open("w") as f:
 f.write("TEST2 — Questions de classement dict v2.2 (avant commit)\n")
 for question,qid in question_ids.items():
  f.write("\n"+qid+" — "+question+"\n")
  for path in sorted({r["path"] for r in unmapped.values() if r["question"]==question}):
   f.write("  "+path+"\n")
write_csv("unmapped.csv",list(unmapped.values()), ["technology","message","path","param_key","discriminator","n_occurrences","question","category_id","subcategory_id","question_id"])

write_csv("path-coverage.csv",coverage)
seed=dict(format_version="2.2",status="REVIEW_REQUIRED",source_project_id="134af70a06eb",
          source="User-provided dict_categories inline specification and paths.csv (SQL included)",
          source_paths_sha256=hashlib.sha256((AUDIT/"paths.csv").read_bytes()).hexdigest(),
          source_populations_sha256=hashlib.sha256((AUDIT/"path-populations.csv").read_bytes()).hexdigest(),
          categories=categories,subcategories=subcategories,maps=list(mapped.values()),
          unresolved=list(unmapped.values()),template_links=[],template_unresolved=[])
templates=json.loads((AUDIT/"templates-before.json").read_text())
seed["template_source_sha256"]=hashlib.sha256(json.dumps(templates,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
links=[];template_questions=[]
for template in templates:
 for entry in template["entries"]:
  matches=[];missing=[]
  if not entry["parameters"]:
   missing.append("Aucun chemin de référence résolu dans le template existant.")
  for ref in entry["parameters"]:
   observed=[r for r in rows if r["system"]==ref["technology"] and r["param_key"]==ref["param_key"]
             and all(r["disc"].get(k)==v for k,v in ref["discriminators"].items())]
   if not observed:
    missing.append("Référence absente de paths.csv après exclusions: "+ref["param_key"])
   for r in observed:
    match=matching(r) if r["origin"]=="network_config" else None
    if match: matches.append(match["subcategory_id"])
    else: missing.append("Chemin observé non classé dans la nouvelle taxonomie: "+r["normalized_path"])
  for subid in sorted(set(matches)):
   links.append(dict(template_category_id=template["category_id"],entry_id=entry["id"],subcategory_id=subid,
                     note="Lien prouvé par paramètres référencés et chemins de TEST2 ; contenu du template inchangé."))
  if missing:
   template_questions.append(dict(template_category_id=template["category_id"],entry_id=entry["id"],label=entry["label"],
      existing_reason=entry.get("reason") or "",proven_subcategories=";".join(sorted(set(matches))),
      question=" | ".join(sorted(set(missing)))+" — préciser la liaison par chemin, pas par libellé."))
seed["template_links"]=links
seed["template_unresolved"]=template_questions
write_csv("template-unmapped.csv",template_questions)
OUTPUT.write_text(json.dumps(seed,indent=2,ensure_ascii=False)+"\n")
(AUDIT/"context-rules.json").write_text(json.dumps(rules,indent=2,ensure_ascii=False)+"\n")
print(json.dumps({"normalized_mapping_rows":len(mapped),"unresolved_populations":len(unmapped),
 "template_links":len(links),"template_questions":len(template_questions),
 "coverage_states":{s:sum(int(r["n_occurrences"]) for r in coverage if r["state"]==s) for s in ["MAPPED","UNRESOLVED","PRESERVED_ROOT"]}},indent=2))
