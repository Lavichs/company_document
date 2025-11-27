from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import select, ForeignKey, delete
import uuid
import pprint
import os
from pathlib import Path
from pydantic import BaseModel
from fastapi import FastAPI, Depends, UploadFile, Request, HTTPException
from typing import Annotated
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
    # for i in range(0, len(lst), n):
    #     chunk = lst[i : i + n]
    #     if len(chunk) < n:
    #         chunk += [None] * (n - len(chunk))
    #     yield chunk


app = FastAPI()


app.mount("/resource", StaticFiles(directory="resource"), name="resource")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

engine = create_async_engine("sqlite+aiosqlite:///resource.db")
new_session = async_sessionmaker(engine, expire_on_commit=False)
templates = Jinja2Templates(directory=".")


class FILE_TYPE:
    file = "file"
    folder = "folder"
    link = "link"


async def get_session():
    async with new_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


class Base(DeclarativeBase):
    pass


class ResourceObjectModel(Base):
    __tablename__ = "resource_object"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    obj_type: Mapped[str] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    href: Mapped[str] = mapped_column(nullable=True)


class ResourceLinkModel(Base):
    __tablename__ = "resource_link"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resource_object.id", ondelete="CASCADE", onupdate="NO ACTION"),
        nullable=False,
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resource_object.id", ondelete="CASCADE", onupdate="NO ACTION"),
        nullable=False,
    )


class ObjAddSchema(BaseModel):
    obj_type: str
    title: str
    href: str | None


class ObjSchema(ObjAddSchema):
    id: uuid.UUID


class FolderSchema(BaseModel):
    title: str


class ObjectRenameSchema(BaseModel):
    title: str


class ResourceObjectService:
    async def getById(self, id: uuid.UUID) -> ResourceObjectModel:
        async with new_session() as session:
            result = await session.execute(
                select(ResourceObjectModel).where(ResourceObjectModel.id == id)
            )
            result = result.first()
            if result is None:
                raise HTTPException(status_code=400, detail="Not found")
            return result[0]

    async def getOneByTitle(self, title: str) -> ResourceObjectModel:
        async with new_session() as session:
            result = await session.execute(
                select(ResourceObjectModel).where(ResourceObjectModel.title == title)
            )
            return result.first()[0]


class ResourceLinkService:
    async def getAllByParent(self, parent_id: uuid.UUID) -> list[ResourceObjectModel]:
        async with new_session() as session:
            result = await session.execute(
                select(ResourceLinkModel).where(
                    ResourceLinkModel.parent_id == parent_id
                )
            )
            return result.scalars().all()


resource_object_service = ResourceObjectService()
resource_link_service = ResourceLinkService()


async def get_page(
    session,
    request: Request,
    is_admin: bool = False,
    page_id: uuid.UUID = None,
):
    if page_id is None:
        obj: ResourceObjectModel = await resource_object_service.getOneByTitle(
            "Ресурсы"
        )
    else:
        obj: ResourceObjectModel = await resource_object_service.getById(page_id)

    obj_child = await resource_link_service.getAllByParent(obj.id)

    items: list[ResourceObjectModel] = []
    for cld in obj_child:
        child_obj = await resource_object_service.getById(cld.child_id)
        items.append(child_obj)

    items = sorted(items, key=lambda x: x.obj_type, reverse=True)
    page_data = {
        "request": request,
        "lists": list(chunks(items, 7)),
        "page_id": obj.id,
        "page": "Ресурсы",
        "href": obj.href,
    }

    if is_admin:
        return templates.TemplateResponse(
            "template_admin.html",
            page_data,
        )
    else:
        return templates.TemplateResponse(
            "template.html",
            page_data,
        )


@app.post("/setup_database")
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with new_session() as session:
        new_obj = ResourceObjectModel(
            id=uuid.uuid4(),
            obj_type=FILE_TYPE.folder,
            title="Ресурсы",
        )
        session.add(new_obj)
        await session.commit()

    return {"ok": True}


@app.get("/")
async def get_home(session: SessionDep, request: Request, response_class=HTMLResponse):
    return await get_page(session, request)


@app.get("/admin")
async def get_home(session: SessionDep, request: Request, response_class=HTMLResponse):
    return await get_page(session, request, is_admin=True)


@app.get("/{id_folder}")
async def get_folder(
    id_folder: uuid.UUID,
    session: SessionDep,
    request: Request,
    response_class=HTMLResponse,
):
    return await get_page(session, request, page_id=id_folder)


@app.get("/admin/{id_folder}")
async def get_folder(
    id_folder: uuid.UUID,
    session: SessionDep,
    request: Request,
    response_class=HTMLResponse,
):
    return await get_page(session, request, page_id=id_folder, is_admin=True)


@app.post("/{id_parent}/add_file")
async def add_file(id_parent: uuid.UUID, session: SessionDep, files: list[UploadFile]):
    await resource_object_service.getById(id_parent)

    for file in files:
        new_obj = ResourceObjectModel(
            id=uuid.uuid4(),
            obj_type=FILE_TYPE.file,
            title=file.filename.split(".")[0],
        )
        new_link = ResourceLinkModel(
            id=uuid.uuid4(), parent_id=id_parent, child_id=new_obj.id
        )

        pth = Path("uploads", f"{new_obj.id}.{file.filename.split(".")[-1]}")
        with open(pth, "wb") as f:
            f.write(file.file.read())

        session.add(new_obj)
        session.add(new_link)
        await session.commit()

    return {"ok": True}


@app.post("/{id_parent}/add_folder")
async def add_folder(id_parent: uuid.UUID, session: SessionDep, data: FolderSchema):
    await resource_object_service.getById(id_parent)

    new_obj = ResourceObjectModel(
        id=uuid.uuid4(),
        obj_type=FILE_TYPE.folder,
        title=data.title,
    )
    new_link = ResourceLinkModel(
        id=uuid.uuid4(), parent_id=id_parent, child_id=new_obj.id
    )

    session.add(new_obj)
    session.add(new_link)
    await session.commit()

    return {"parent_id": id_parent, "title": data.title}


@app.post("/{id_parent}/add_link")
async def add_file(id_parent: uuid.UUID, session: SessionDep, data: ObjAddSchema):
    await resource_object_service.getById(id_parent)

    new_obj = ResourceObjectModel(
        id=uuid.uuid4(), obj_type=FILE_TYPE.link, title=data.title, href=data.href
    )
    new_link = ResourceLinkModel(
        id=uuid.uuid4(), parent_id=id_parent, child_id=new_obj.id
    )

    session.add(new_obj)
    session.add(new_link)
    await session.commit()

    return {"ok": True, "data": new_obj}


@app.post("/{id_link}/change_image")
async def add_file(id_link: uuid.UUID, session: SessionDep, files: list[UploadFile]):
    obj = await resource_object_service.getById(id_link)
    file = files[0]
    print(file)

    if file.filename.split(".")[-1] != "png":
        raise HTTPException(status_code=400, detail="Not valid PNG")

    pth = Path("resource/links", f"{obj.id}.png")
    with open(pth, "wb") as f:
        f.write(file.file.read())

    return {"ok": True, "data": pth}


@app.delete("/{obj_id}")
async def delete_object(obj_id: uuid.UUID, session: SessionDep):
    async def helper(o_id: uuid.UUID):
        object_res = await resource_object_service.getById(o_id)

        if object_res.obj_type == FILE_TYPE.file:
            os.remove(Path("uploads", f"{object_res.id}.pdf"))
        elif object_res.obj_type == FILE_TYPE.folder:
            folder_child = await resource_link_service.getAllByParent(o_id)
            if folder_child:  # folder has child
                for children in folder_child:  # перебрать все вложенные объекты
                    await helper(children.child_id)  # удалить все вложенные объекты
        elif object_res.obj_type == FILE_TYPE.link:
            os.remove(Path("resource/links", f"{object_res.id}.png"))
        else:
            pass

        await session.execute(
            delete(ResourceObjectModel).where(ResourceObjectModel.id == obj_id)
        )
        await session.execute(
            delete(ResourceLinkModel).where(ResourceLinkModel.child_id == obj_id)
        )
        await session.commit()
        # end helper func

    obj = await resource_object_service.getById(obj_id)
    await helper(obj.id)

    return {"ok": True, "obj.obj_type": obj.obj_type}


@app.put("/{obj_id}/rename")
async def rename_object(
    obj_id: uuid.UUID, session: SessionDep, data: ObjectRenameSchema
):
    obj = await resource_object_service(obj_id)

    obj.title = data.title
    await session.commit()

    return {"ok": True}
