from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import select, ForeignKey, delete
import uuid
import pprint
import os
from pathlib import Path
from pydantic import BaseModel
from fastapi import FastAPI, Depends, UploadFile, Request
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


class ObjSchema(ObjAddSchema):
    id: uuid.UUID


class FolderSchema(BaseModel):
    title: str


class ObjectRenameSchema(BaseModel):
    title: str


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
    root_obj = await session.execute(
        select(ResourceObjectModel).where(ResourceObjectModel.title == "Ресурсы")
    )
    root_id = root_obj.first()[0].id
    res = await session.execute(
        select(ResourceLinkModel).where(ResourceLinkModel.parent_id == root_id)
    )
    root_child = res.scalars().all()

    items = []
    for cld in root_child:
        children = await session.execute(
            select(ResourceObjectModel).where(ResourceObjectModel.id == cld.child_id)
        )
        child_obj = children.first()[0]
        items.append(child_obj)
    
    items = sorted(items, key=lambda x: x.obj_type, reverse=True)

    return templates.TemplateResponse(
        "template.html",
        {
            "request": request,
            "lists": list(chunks(items, 6)),
            "page_id": root_id,
            "page": "Ресурсы",
        },
    )


@app.get("/admin")
async def get_home(session: SessionDep, request: Request, response_class=HTMLResponse):
    root_obj = await session.execute(
        select(ResourceObjectModel).where(ResourceObjectModel.title == "Ресурсы")
    )
    root_id = root_obj.first()[0].id
    res = await session.execute(
        select(ResourceLinkModel).where(ResourceLinkModel.parent_id == root_id)
    )
    root_child = res.scalars().all()

    items = []
    for cld in root_child:
        children = await session.execute(
            select(ResourceObjectModel).where(ResourceObjectModel.id == cld.child_id)
        )
        child_obj = children.first()[0]
        items.append(child_obj)
    
    items = sorted(items, key=lambda x: x.obj_type, reverse=True)

    return templates.TemplateResponse(
        "template_admin.html",
        {
            "request": request,
            "lists": list(chunks(items, 6)),
            "page_id": root_id,
            "page": "Ресурсы",
        },
    )

@app.get("/{id_folder}")
async def get_folder(
    id_folder: uuid.UUID,
    session: SessionDep,
    request: Request,
    response_class=HTMLResponse,
):
    if id_folder == "":
        folder_obj = await session.execute(
            select(ResourceObjectModel).where(ResourceObjectModel.title == "Ресурсы")
        )
    else:
        folder_obj = await session.execute(
            select(ResourceObjectModel).where(ResourceObjectModel.id == id_folder)
        )
    folder = folder_obj.first()[0]
    res = await session.execute(
        select(ResourceLinkModel).where(ResourceLinkModel.parent_id == folder.id)
    )
    folder_child = res.scalars().all()

    items = []
    for cld in folder_child:
        children = await session.execute(
            select(ResourceObjectModel).where(ResourceObjectModel.id == cld.child_id)
        )
        child_obj = children.first()[0]
        items.append(child_obj)
    
    items = sorted(items, key=lambda x: x.obj_type, reverse=True)

    return templates.TemplateResponse(
        "template.html",
        {
            "request": request,
            "lists": list(chunks(items, 6)),
            "page_id": folder.id,
            "page": folder.title,
        },
    )


@app.get("/admin/{id_folder}")
async def get_folder(
    id_folder: uuid.UUID,
    session: SessionDep,
    request: Request,
    response_class=HTMLResponse,
):
    if id_folder == "":
        folder_obj = await session.execute(
            select(ResourceObjectModel).where(ResourceObjectModel.title == "Ресурсы")
        )
    else:
        folder_obj = await session.execute(
            select(ResourceObjectModel).where(ResourceObjectModel.id == id_folder)
        )
    folder = folder_obj.first()[0]
    res = await session.execute(
        select(ResourceLinkModel).where(ResourceLinkModel.parent_id == folder.id)
    )
    folder_child = res.scalars().all()

    items = []
    for cld in folder_child:
        children = await session.execute(
            select(ResourceObjectModel).where(ResourceObjectModel.id == cld.child_id)
        )
        child_obj = children.first()[0]
        items.append(child_obj)
    
    items = sorted(items, key=lambda x: x.obj_type, reverse=True)

    return templates.TemplateResponse(
        "template_admin.html",
        {
            "request": request,
            "lists": list(chunks(items, 6)),
            "page_id": folder.id,
            "page": folder.title,
        },
    )


@app.post("/{id_parent}/add_file")
async def add_file(id_parent: uuid.UUID, session: SessionDep, files: list[UploadFile]):
    result = await session.execute(
        select(ResourceObjectModel).where(ResourceObjectModel.id == id_parent)
    )
    if result.first() is None:
        return "Not found"

    for file in files:
        print(file.filename)
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

        print(new_obj)
        session.add(new_obj)
        session.add(new_link)
        await session.commit()

    return {"ok": True}


@app.post("/{id_parent}/add_folder")
async def add_folder(id_parent: uuid.UUID, session: SessionDep, data: FolderSchema):
    result = await session.execute(
        select(ResourceObjectModel).where(ResourceObjectModel.id == id_parent)
    )
    if result.first() is None:
        return "Not found"

    new_obj = ResourceObjectModel(
        id=uuid.uuid4(),
        obj_type=FILE_TYPE.folder,
        title=data.title,
    )
    new_link = ResourceLinkModel(
        id=uuid.uuid4(), parent_id=id_parent, child_id=new_obj.id
    )

    print(new_obj)
    session.add(new_obj)
    session.add(new_link)
    await session.commit()

    return {"parent_id": id_parent, "title": data.title}


@app.delete("/{obj_id}")
async def delete_object(obj_id: uuid.UUID, session: SessionDep):
    async def helper(o_id: uuid.UUID):
        res = await session.execute(
            select(ResourceObjectModel).where(ResourceObjectModel.id == o_id)
        )
        object_res = res.first()[0]

        if object_res.obj_type == "file":
            os.remove(Path("uploads", f"{object_res.id}.pdf"))
        elif object_res.obj_type == "folder":
            res = await session.execute(
                select(ResourceLinkModel).where(ResourceLinkModel.parent_id == o_id)
            )
            folder_child = res.scalars().all()
            if folder_child:    # folder has child
                for children in folder_child:   # перебрать все вложенные объекты
                    await helper(children.child_id)   # удалить все вложенные объекты
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

    result = await session.execute(
        select(ResourceObjectModel).where(ResourceObjectModel.id == obj_id)
    )
    obj = result.first()
    if obj is None:
        return "Not found"
    obj = obj[0]
    await helper(obj.id)

    return {"ok": True, "obj.obj_type": obj.obj_type}


@app.put('/{obj_id}/rename')
async def rename_object(obj_id: uuid.UUID, session: SessionDep, data: ObjectRenameSchema):
    result = await session.execute(
        select(ResourceObjectModel).where(ResourceObjectModel.id == obj_id)
    )
    obj = result.first()
    if obj is None:
        return "Not found"
    
    obj = obj[0]

    obj.title = data.title
    await session.commit()

    return {"ok": True}

