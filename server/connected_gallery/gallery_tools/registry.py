from __future__ import annotations
import base64
import hashlib
import io
import json
import time
from datetime import datetime
from pydantic import BaseModel, Field, model_validator
from connected_gallery.domain.models import (
    Box,
    PhotoAnalysis,
    ExplorationResult,
    SpaceProposal,
)
from connected_gallery.adapters.store import encoded
from connected_gallery.agent_specs.budgets import run_timeout


class InspectArgs(BaseModel):
    photo_ids: list[str] = Field(max_length=8)


class RegionArgs(BaseModel):
    photo_id: str
    box: Box | None = None


class ListArgs(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class GroundArgs(RegionArgs):
    query: str


class EmbedArgs(BaseModel):
    photo_ids: list[str] = Field(default_factory=list, max_length=8)
    regions: list[RegionArgs] = Field(default_factory=list, max_length=8)
    include_text: bool = True


class SearchArgs(BaseModel):
    query: str
    limit: int = Field(default=20, ge=1, le=100)


class VisualArgs(BaseModel):
    query: str = ""
    photo_id: str | None = None
    box: Box | None = None
    limit: int = Field(default=20, ge=1, le=100)


class FaceArgs(RegionArgs):
    face_index: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class LocationArgs(BaseModel):
    latitude: float
    longitude: float
    radius_km: float = Field(gt=0, le=20040)


class TimeArgs(BaseModel):
    start: datetime
    end: datetime
    center: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def window(self):
        if any(d.tzinfo is None for d in (self.start, self.end, self.center) if d is not None):
            raise ValueError("Use timezone-aware timestamps")
        if self.start > self.end:
            raise ValueError("Time window start must precede end")
        if self.center is not None and not self.start <= self.center <= self.end:
            raise ValueError("Center must be inside the chosen time window")
        return self


class GalleryTools:
    def __init__(self, store, models, request, run_id):
        self.store = store
        self.models = models
        self.request = request
        self.run_id = run_id
        self.deadline = (
            time.monotonic()
            + run_timeout(request.role)
        )
        self.seen = set()
        self.covered = set()
        self.searched = set()
        self.result = None
        self.defer_results = False
        self.versions = {p.id: p.version for p in store.photos()}
        self.definitions = {
            "list_photos": (
                ListArgs,
                "Page through photo metadata and existing analysis.",
            ),
            "inspect_photos": (
                InspectArgs,
                "View up to 8 actual photo images. Required before selecting results.",
            ),
            "inspect_region": (
                RegionArgs,
                "View an actual image crop; coordinates are normalized in the oriented image.",
            ),
            "recognize_text": (
                RegionArgs,
                "Read text using Korean OCR. Returns recognition evidence and normalized x,y,width,height "
                "boxes in the FULL oriented photo, even for a crop. Copy matching boxes directly.",
            ),
            "ground_regions": (
                GroundArgs,
                "Find objects for a descriptive query. Returns normalized x,y,width,height boxes "
                "in the FULL oriented photo, even when searching a crop. Copy these boxes directly.",
            ),
            "analyze_faces": (
                RegionArgs,
                "Detect faces and index face embeddings; does not identify names. "
                "Boxes are normalized x,y,width,height in the FULL oriented photo.",
            ),
            "ensure_embeddings": (
                EmbedArgs,
                "Create/reuse image and optional existing description embeddings.",
            ),
            "search_visual": (
                VisualArgs,
                "Find visual candidates by text or photo/crop. Candidate vectors must exist.",
            ),
            "search_text": (
                SearchArgs,
                "Retrieve text evidence by semantic embedding and literal text independently.",
            ),
            "search_faces": (
                FaceArgs,
                "Search by a selected detected face index in source photo/crop.",
            ),
            "search_location": (
                LocationArgs,
                "Retrieve photos within an explicitly chosen radius.",
            ),
            "search_time": (
                TimeArgs,
                "Retrieve candidates in a time window YOU choose, nearest the optional center. "
                "User year remains enforced. Time proximity is not proof of the same event; inspect images.",
            ),
            "read_spaces": (
                ListArgs,
                "Read existing Spaces and explicit user feedback.",
            ),
        }
        if request.role != "organizer":
            self.definitions.pop("read_spaces")
        submit = {
            "analyst": ("submit_photo_analysis", PhotoAnalysis),
            "explorer": ("submit_exploration_result", ExplorationResult),
            "organizer": ("submit_space_proposal", SpaceProposal),
        }[request.role]
        self.definitions[submit[0]] = (
            submit[1],
            "Validate and persist your evidence-grounded result. Use actual IDs only.",
        )
        if request.role == "analyst":
            observation_tools = {"inspect_photos", "inspect_region", "recognize_text",
                                 "ground_regions", "analyze_faces", "ensure_embeddings",
                                 "submit_photo_analysis"}
            self.definitions = {k: v for k, v in self.definitions.items() if k in observation_tools}

    def schemas(self):
        return [
            {"name": n, "description": d, "input_schema": m.model_json_schema()}
            for n, (m, d) in self.definitions.items()
        ]

    def allowed(self):
        year = self.request.explore.year if self.request.explore else None
        return {p.id for p in self.store.photos(year)}

    def candidate_ids(self):
        ids = self.allowed()
        if self.request.explore:
            ids.discard(self.request.explore.anchor.photo_id)
        return ids

    def authorize(self, photo_id, source=True):
        if time.monotonic() > self.deadline:
            raise ValueError("Run deadline exceeded")
        states = self.store.rows("SELECT status FROM runs WHERE id=?", (self.run_id,))
        if states and states[0]["status"] not in ("running", "queued"):
            raise ValueError("Run is no longer active")
        p = self.store.photo(photo_id)
        if self.versions.get(photo_id) != p.version:
            raise ValueError("Photo changed during run; start a new run")
        seeds = set(self.request.photo_ids)
        if self.request.explore:
            seeds.add(self.request.explore.anchor.photo_id)
        if photo_id not in self.allowed() and not (source and photo_id in seeds):
            raise ValueError("Photo outside selected year")
        return p

    def image_block(self, photo_id, box=None):
        asset = self.authorize(photo_id)
        image = self.store.read_image(photo_id, box)
        image.thumbnail((1536, 1536))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=85)
        self.seen.add(photo_id)
        return [
            {
                "type": "text",
                "text": encoded(
                    {
                        "photo_id": photo_id,
                        "captured_at": asset.captured_at,
                        "time_source": asset.time_source,
                        # A whole-photo caption can describe objects outside a crop
                        # and must not substitute for the selected visual evidence.
                        "analysis": self.store.analysis(photo_id) if box is None else None,
                        "box": box.model_dump() if box else None,
                    }
                ),
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(out.getvalue()).decode(),
                },
            },
        ]

    def artifact(self, name, args, fn):
        p = self.authorize(args.photo_id)
        key = hashlib.sha256(
            encoded(
                [
                    name,
                    p.id,
                    p.version,
                    args.model_dump(),
                    self.models.pins if hasattr(self.models, "pins") else {},
                ]
            ).encode()
        ).hexdigest()
        rows = self.store.rows("SELECT data FROM artifacts WHERE key=?", (key,))
        if rows:
            return json.loads(rows[0]["data"])
        value = fn(self.store.read_image(p.id, args.box))
        self.authorize(p.id)
        self.store.write(
            "INSERT OR REPLACE INTO artifacts VALUES(?,?,?)",
            (key, p.id, encoded(value)),
        )
        return value

    def invoke(self, name, raw):
        if name not in self.definitions:
            raise ValueError("Unknown tool")
        args = self.definitions[name][0].model_validate(raw)
        if name.startswith("submit_") and name != "submit_photo_analysis":
            with self.store.lock:
                result = getattr(self, name)(args)
        else:
            result = getattr(self, name)(args)
        self.store.event(
            self.run_id,
            "tool",
            {
                "name": name,
                "seen": sorted(self.seen),
                "covered": sorted(self.covered),
                "searched": sorted(self.searched),
            },
        )
        return result

    def coverage_status(self):
        photos = self.store.photos(self.request.explore.year if self.request.explore else None)
        return {"covered_count": sum(p.id in self.covered for p in photos),
                "total_count": len(photos),
                "next_uncovered_offset": next((i for i, p in enumerate(photos) if p.id not in self.covered), None)}

    def list_photos(self, args):
        photos = self.store.photos(
            self.request.explore.year if self.request.explore else None
        )
        page = photos[args.offset : args.offset + args.limit]
        self.covered.update(p.id for p in page)
        output = []
        for p in page:
            analysis = self.store.analysis(p.id)
            # Bound transport context for 1,000 photos; full evidence is available via inspection.
            summary = (
                None
                if analysis is None
                else {
                    "description_excerpt": analysis["description"][:160],
                    "ocr_excerpt": analysis.get("ocr", "")[:64],
                    "region_count": len(analysis.get("regions", [])),
                    "truncated": len(analysis["description"]) > 160
                    or len(analysis.get("ocr", "")) > 64,
                }
            )
            output.append(
                {
                    "photo_id": p.id,
                    "captured_at": p.captured_at,
                    "time_source": p.time_source,
                    "summary": summary,
                    "image_ready": self.store.image_path(p.id).exists(),
                }
            )
        return {
            "total": len(photos),
            "next_offset": args.offset + len(page),
            "coverage": self.coverage_status(),
            "photos": output,
        }

    def inspect_photos(self, args):
        content = []
        for pid in args.photo_ids:
            content += self.image_block(pid)
        return content

    def inspect_region(self, args):
        return self.image_block(args.photo_id, args.box)

    def recognize_text(self, args):
        result = self.artifact("ocr-v1", args, self.models.ocr)
        image = self.store.read_image(args.photo_id, args.box)
        texts = []
        for page in result["pages"]:
            evidence = page.get("res", page)
            for text, score, xyxy in zip(evidence["rec_texts"], evidence["rec_scores"],
                                         evidence["rec_boxes"], strict=True):
                box = self.pixel_box(xyxy, image.size, args.box)
                if box is not None:
                    texts.append({"text": text, "score": score, "box": box})
        return {"coordinate_space": "full_oriented_photo_normalized_xywh", "texts": texts}

    def ground_regions(self, args):
        result = self.artifact(
            "ground-v1", args, lambda im: self.models.ground(im, args.query)
        )
        # Cached detector evidence is pixel xyxy in the exact input image.
        # Convert here, not in the language model: uploaded previews can have
        # different dimensions from PhotoAsset and a crop has a different origin.
        image = self.store.read_image(args.photo_id, args.box)
        labels = result.get("text_labels", result.get("labels", []))
        detections = []
        for i, xyxy in enumerate(result["boxes"]):
            box = self.pixel_box(xyxy, image.size, args.box)
            if box is None:
                continue
            detections.append({"index": i, "label": labels[i],
                               "score": result["scores"][i], "box": box})
        return {"coordinate_space": "full_oriented_photo_normalized_xywh",
                "detections": detections}

    @classmethod
    def pixel_box(cls, xyxy, size, crop):
        left, top, right, bottom = xyxy
        width, height = size
        left, right = max(0, left / width), min(1, right / width)
        top, bottom = max(0, top / height), min(1, bottom / height)
        if right <= left or bottom <= top:
            return None
        return cls.full_photo_box({"x": left, "y": top, "width": right - left,
                                   "height": bottom - top}, crop)

    @staticmethod
    def full_photo_box(box, crop):
        local = Box.model_validate(box)
        if crop is None:
            return local.model_dump()
        return Box(x=crop.x + local.x * crop.width,
                   y=crop.y + local.y * crop.height,
                   width=local.width * crop.width,
                   height=local.height * crop.height).model_dump()

    def analyze_faces(self, args):
        result = self.artifact("sface-v1", args, self.models.faces)
        face_list = []
        for i, f in enumerate(result["faces"]):
            key = f"{args.photo_id}:face:{hashlib.sha256(encoded(args.model_dump()).encode()).hexdigest()[:12]}:{i}"
            self.store.vector(key, args.photo_id, "sface", f["vector"])
            face_list.append({"index": i, "box": self.full_photo_box(f["box"], args.box), "artifact": key})
        return {"coordinate_space": "full_oriented_photo_normalized_xywh", "faces": face_list}

    def ensure_embeddings(self, args):
        results = []
        for pid in args.photo_ids:
            p = self.authorize(pid)
            key = f"{pid}:image:{p.version}:{self.models.visual_space}"
            if not self.store.rows("SELECT key FROM vectors WHERE key=?", (key,)):
                space, vec = self.models.image(self.store.read_image(pid))
                self.store.vector(key, pid, space, vec)
            a = self.store.analysis(pid)
            if args.include_text and a:
                text = a["description"] + " " + a.get("ocr", "")
                tkey = f"{pid}:text:{hashlib.sha256(text.encode()).hexdigest()}:{self.models.text_space}"
                if not self.store.rows("SELECT key FROM vectors WHERE key=?", (tkey,)):
                    space, vec = self.models.text(text, query=False)
                    self.store.vector(tkey, pid, space, vec)
            results.append(pid)
        for region in args.regions:
            p = self.authorize(region.photo_id)
            key = (
                f"{p.id}:crop:"
                + hashlib.sha256(
                    encoded(
                        [p.version, region.model_dump(), self.models.visual_space]
                    ).encode()
                ).hexdigest()
            )
            if not self.store.rows("SELECT key FROM vectors WHERE key=?", (key,)):
                space, vec = self.models.image(self.store.read_image(p.id, region.box))
                self.authorize(p.id)
                self.store.vector(key, p.id, space, vec)
            results.append(key)
        return {"indexed": results}

    def index_coverage(self, space):
        indexed = {
            r["photo_id"]
            for r in self.store.rows(
                "SELECT DISTINCT photo_id FROM vectors WHERE space=?", (space,)
            )
        } & self.candidate_ids()
        self.searched.update(indexed)
        missing = self.candidate_ids() - indexed
        return {
            "indexed_count": len(indexed),
            "eligible_count": len(self.candidate_ids()),
            "unindexed_ids": sorted(missing)[:20],
            "unindexed_count": len(missing),
        }

    def search_visual(self, args):
        if args.photo_id:
            self.authorize(args.photo_id)
            space, vec = self.models.image(
                self.store.read_image(args.photo_id, args.box)
            )
        elif args.query:
            space, vec = self.models.text(args.query, visual=True)
        else:
            raise ValueError("A query or image is required")
        return {
            "candidates": self.store.search(space, vec, self.candidate_ids(), args.limit),
            "coverage": self.index_coverage(space),
        }

    def search_text(self, args):
        allowed = self.candidate_ids()
        # Literal and semantic channels are separate evidence, never fixed-score fusion.
        literal = []
        if args.query.strip():
            query = '"' + args.query.replace('"', '""') + '"'
            literal = [
                {"photo_id": r["photo_id"]}
                for r in self.store.rows(
                    "SELECT photo_id FROM evidence_fts WHERE evidence_fts MATCH ?",
                    (query,),
                )
                if r["photo_id"] in allowed
            ][: args.limit]
        try:
            space, vec = self.models.text(args.query)
            semantic = self.store.search(space, vec, allowed, args.limit)
            error = None
        except Exception as e:
            semantic = []
            error = type(e).__name__
        return {
            "literal": literal,
            "semantic": semantic,
            "semantic_error": error,
            "coverage": self.index_coverage(self.models.text_space),
        }

    def search_faces(self, args):
        result = self.artifact(
            "sface-v1",
            RegionArgs(photo_id=args.photo_id, box=args.box),
            self.models.faces,
        )
        if args.face_index >= len(result["faces"]):
            raise ValueError("Face index not found")
        return {
            "candidates": self.store.search(
                "sface",
                result["faces"][args.face_index]["vector"],
                self.candidate_ids(),
                args.limit,
            )
        }

    def search_location(self, args):
        import math

        hits = []
        eligible = self.candidate_ids()
        for p in self.store.photos(
            self.request.explore.year if self.request.explore else None
        ):
            if p.id not in eligible or p.latitude is None or p.longitude is None:
                continue
            lat1, lat2 = map(math.radians, (args.latitude, p.latitude))
            dlat = lat2 - lat1
            dlon = math.radians(p.longitude - args.longitude)
            distance = (
                6371
                * 2
                * math.asin(
                    min(
                        1,
                        math.sqrt(
                            math.sin(dlat / 2) ** 2
                            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                        ),
                    )
                )
            )
            if distance <= args.radius_km:
                hits.append({"photo_id": p.id, "distance_km": distance})
        return {"candidates": hits}

    def read_spaces(self, args):
        return {
            "spaces": self.store.spaces(),
            "feedback": [
                json.loads(r["data"])
                for r in self.store.rows("SELECT data FROM feedback")
            ],
        }

    def search_time(self, args):
        photos = self.store.photos(self.request.explore.year if self.request.explore else None)
        eligible = self.candidate_ids()
        center = args.center or args.start + (args.end - args.start) / 2
        candidates = []
        unknown = 0
        for p in photos:
            if p.id not in eligible:
                continue
            if p.captured_at is None or p.captured_at.tzinfo is None or p.time_source not in ("exif", "media_store"):
                unknown += 1
                continue
            if args.start <= p.captured_at <= args.end:
                candidates.append({"photo_id": p.id, "captured_at": p.captured_at,
                                   "time_source": p.time_source,
                                   "distance_seconds": abs((p.captured_at - center).total_seconds())})
        candidates.sort(key=lambda p: p["distance_seconds"])
        return {"candidates": candidates[:args.limit], "total_in_window": len(candidates),
                "unknown_capture_time_count": unknown,
                "constraint": "Temporal candidates only. Inspect images before declaring a shared event."}

    def submit_photo_analysis(self, args):
        if args.photo_id != self.request.photo_ids[0] or args.photo_id not in self.seen:
            raise ValueError("Inspect requested photo before submission")
        self.authorize(args.photo_id)
        # Indexing encodes the photo and the agent's evidence; it makes no
        # semantic decisions. Compute outside the repository lock, then commit both.
        from connected_gallery.application.indexing import AnalysisIndexing
        version = self.versions[args.photo_id]
        vectors = AnalysisIndexing(self.store, self.models).prepare(args, version) if self.models is not None else []
        with self.store.lock:
            self.authorize(args.photo_id)
            persisted_run = self.store.rows("SELECT id FROM runs WHERE id=?", (self.run_id,))
            self.store.save_analysis(args, vectors=vectors, expected_version=version,
                                     run_id=self.run_id if persisted_run else None)
            self.result = args.model_dump(mode="json")
        return {"saved": True}

    def submit_exploration_result(self, args):
        ids = [x.photo_id for x in args.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate result IDs")
        if (
            not ids
            and args.complete
            and not self.allowed().issubset(self.seen | self.searched)
        ):
            raise ValueError(
                "Unsearched photos remain. An empty index is not evidence of no matches. Inspect unindexed photos or submit incomplete."
            )
        anchor = self.request.explore.anchor.photo_id
        if anchor in ids:
            raise ValueError("The anchor photo is already being viewed; return other verified photos")
        if anchor not in self.seen:
            raise ValueError("Inspect anchor first")
        for pid in ids:
            self.authorize(pid, source=False)
            if pid not in self.seen:
                raise ValueError("Inspect candidate images before selecting them")
        self.result = args.model_dump(mode="json")
        if not self.defer_results:
            self.store.event(self.run_id, "results", self.result)
        else:
            self.store.event(self.run_id, "candidate_proposal", self.result)
        return {"saved": True, "complete": args.complete}

    def submit_space_proposal(self, args):
        if not self.allowed().issubset(self.covered):
            coverage = self.coverage_status()
            raise ValueError(f"Page through the whole library before finalizing Spaces. "
                             f"Covered {coverage['covered_count']}/{coverage['total_count']}; "
                             f"list_photos next_uncovered_offset={coverage['next_uncovered_offset']}.")
        edits = [
            json.loads(r["data"]) for r in self.store.rows("SELECT data FROM feedback")
        ]
        old = {s["id"]: s for s in self.store.spaces()}
        incoming = {s.id: s.model_dump() for s in args.spaces}
        # Preserve explicitly edited Spaces, even when the agent omits one from a new proposal.
        for edit in edits:
            sid = edit.get("space_id")
            if sid in old and sid not in incoming:
                incoming[sid] = old[sid]
        for sid, space in incoming.items():
            for item in space["items"]:
                self.authorize(item["photo_id"])
            for edit in edits:
                if edit.get("space_id") != sid:
                    continue
                pid = edit.get("photo_id")
                if edit["kind"] == "space_exclude":
                    space["items"] = [x for x in space["items"] if x["photo_id"] != pid]
                elif (
                    edit["kind"] == "space_include"
                    and pid in self.allowed()
                    and not any(x["photo_id"] == pid for x in space["items"])
                ):
                    space["items"].append(
                        {"photo_id": pid, "reason": "사용자가 포함한 사진"}
                    )
        if getattr(self, "defer_spaces", False):
            self.result = {"spaces": list(incoming.values())}
            self.store.event(self.run_id, "space_candidate_proposal", self.result)
            return {"saved": False, "pending_review": True}
        with self.store.lock, self.store.db:
            states = self.store.rows("SELECT status FROM runs WHERE id=?", (self.run_id,))
            if states and states[0]["status"] not in ("running", "queued"):
                raise ValueError("Run is no longer active")
            for space in incoming.values():
                for item in space["items"]:
                    self.authorize(item["photo_id"])
            self.store.db.execute("DELETE FROM spaces")
            for sid, space in incoming.items():
                self.store.db.execute(
                    "INSERT INTO spaces VALUES(?,?)", (sid, encoded(space))
                )
        self.store.bump()
        self.result = {"spaces": list(incoming.values())}
        return {"saved": True}
