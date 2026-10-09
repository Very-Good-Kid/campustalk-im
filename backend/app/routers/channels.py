"""频道内容域端点：帖子 / 评论 / 点赞（信息结构图 ⑥ 内容社区·内容层）。

频道容器复用 conversation 表（type='channel'）；本路由只挂内容层接口，
与 messages.py 的实时消息流相互独立。加入免审（见 conversations.join），
但浏览与发言均要求"已是频道成员"——免审进入 ≠ 免审发言。

排序约定：时间序 = 置顶优先再按创建时间倒序；热度序 = 置顶优先再按
点赞数、评论数倒序。软删内容（status=0）不出现在列表与详情中。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sensitive import hit_sensitive
from app.database import get_db
from app.deps import get_current_user
from app.models import Comment, Conversation, Like, Post, User
from app.models.base import utcnow
from app.services.conversation_service import assert_member as _assert_member
from app.services.conversation_service import (
    require_owner_or_admin as _require_role,
)

router = APIRouter(prefix="/api/conversations", tags=["channel-content"])

LIKE_POST = 1
LIKE_COMMENT = 2
MAX_IMAGES = 9


# ---------- 请求 / 响应模型 ----------

class PostAuthorOut(BaseModel):
    user_id: int
    nickname: str
    avatar_url: str | None = None


class PostOut(BaseModel):
    id: int
    channel_id: int
    author: PostAuthorOut
    content: str
    images: list[str] = []
    # 名片帖：被推荐用户信息；非名片帖为 None
    card: PostAuthorOut | None = None
    like_count: int
    comment_count: int
    is_pinned: bool
    liked_by_me: bool = False
    created_at: object
    updated_at: object


class CommentOut(BaseModel):
    id: int
    post_id: int
    author: PostAuthorOut | None = None  # 软删评论作者置空
    parent_id: int | None = None
    parent_author: str | None = None  # 二级回复展示"回复 @某人"
    content: str
    like_count: int
    liked_by_me: bool = False
    created_at: object


class PostCreateIn(BaseModel):
    content: str = Field(default="", max_length=5000)
    images: list[str] = Field(default_factory=list)
    # 分享好友名片：被推荐用户 id（此时 content / images 可为空）
    card_user_id: int | None = None


class CommentCreateIn(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    parent_id: int | None = None


# ---------- 内部工具 ----------

async def _channel_or_404(db: AsyncSession, conversation_id: int) -> Conversation:
    """取频道会话；不存在或类型不是 channel 一律 404（防止把群聊当频道操作）。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.type != "channel":
        raise HTTPException(status_code=404, detail="频道不存在")
    return conv


async def _post_or_404(db: AsyncSession, conversation_id: int, post_id: int) -> Post:
    """取帖子：必须属于该频道且未被软删（status == 1），否则 404。"""
    post = await db.get(Post, post_id)
    if post is None or post.channel_id != conversation_id or post.status != 1:
        raise HTTPException(status_code=404, detail="帖子不存在或已删除")
    return post


async def _author_map(db: AsyncSession, user_ids: set[int]) -> dict[int, User]:
    """批量取作者，避免列表接口逐个查询导致 N+1。"""
    rows = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {u.id: u for u in rows.scalars()}


def _post_out(post: Post, author: User, liked: bool, card_author: User | None = None) -> PostOut:
    """组装帖子响应；``card_author`` 非空即表示这是名片帖（前端渲染名片卡）。"""
    return PostOut(
        id=post.id,
        channel_id=post.channel_id,
        author=PostAuthorOut(
            user_id=author.id, nickname=author.nickname, avatar_url=author.avatar_url
        ),
        content=post.content,
        images=post.images or [],
        card=(
            PostAuthorOut(
                user_id=card_author.id,
                nickname=card_author.nickname,
                avatar_url=card_author.avatar_url,
            )
            if card_author is not None
            else None
        ),
        like_count=post.like_count,
        comment_count=post.comment_count,
        is_pinned=post.is_pinned,
        liked_by_me=liked,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


async def _liked_ids(
    db: AsyncSession, user_id: int, target_type: int, target_ids: set[int]
) -> set[int]:
    """查"我点过赞"的目标 id 集合，供列表一次性标记 ``liked_by_me``，避免逐个查询。"""
    if not target_ids:
        return set()
    rows = await db.execute(
        select(Like.target_id).where(
            Like.user_id == user_id,
            Like.target_type == target_type,
            Like.target_id.in_(target_ids),
        )
    )
    return set(rows.scalars())


def _validate_images(images: list[str]) -> None:
    """校验帖子配图：最多 ``MAX_IMAGES`` 张，且必须是上传接口返回的 ``/uploads/`` URL。"""
    if len(images) > MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"图片最多 {MAX_IMAGES} 张")
    for url in images:
        if not url.startswith("/uploads/"):
            raise HTTPException(status_code=400, detail="图片需先通过上传接口获取 URL")


# ---------- 帖子 ----------

@router.get("/{conversation_id}/posts", response_model=list[PostOut])
async def post_list(
    conversation_id: int,
    sort: str = Query(default="time", pattern="^(time|hot)$"),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """频道帖子流（仅频道成员可见）。

    参数:
        sort: ``time`` = 置顶优先 + 创建时间倒序；
              ``hot``  = 置顶优先 + 点赞数 + 评论数 + 创建时间倒序。
        limit / offset: 普通分页（帖子量级小，未做游标分页）。

    软删帖子（status=0）不会出现在结果中；``liked_by_me`` 标记当前用户是否已点赞。
    """
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)

    stmt = select(Post).where(
        Post.channel_id == conversation_id, Post.status == 1
    )
    if sort == "hot":
        stmt = stmt.order_by(
            Post.is_pinned.desc(), Post.like_count.desc(), Post.comment_count.desc(),
            Post.created_at.desc(), Post.id.desc(),
        )
    else:
        stmt = stmt.order_by(Post.is_pinned.desc(), Post.created_at.desc(), Post.id.desc())
    stmt = stmt.limit(limit).offset(offset)

    posts = (await db.execute(stmt)).scalars().all()
    authors = await _author_map(db, {p.author_id for p in posts})
    card_ids = {p.card_user_id for p in posts if p.card_user_id}
    card_authors = await _author_map(db, card_ids) if card_ids else {}
    liked = await _liked_ids(db, current.id, LIKE_POST, {p.id for p in posts})

    return [
        _post_out(p, authors[p.author_id], p.id in liked, card_authors.get(p.card_user_id))
        for p in posts
        if p.author_id in authors
    ]


@router.post("/{conversation_id}/posts", response_model=PostOut, status_code=201)
async def create_post(
    conversation_id: int,
    body: PostCreateIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发帖：正文 / 配图 / 名片三者至少一项非空。

    与消息域共用 ``core.sensitive`` 做敏感词过滤（命中即 400 且不落库）；
    配图必须是上传接口返回的 URL；名片帖校验被推荐用户存在且不是机器人。
    """
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)

    content = body.content.strip()
    images = [url.strip() for url in body.images if url and url.strip()]

    # 名片帖：验证被推荐用户存在（机器人不可被推荐）
    card_author = None
    if body.card_user_id is not None:
        card_author = await db.get(User, body.card_user_id)
        if card_author is None or card_author.is_bot:
            raise HTTPException(status_code=400, detail="被推荐的用户不存在")

    if not content and not images and card_author is None:
        raise HTTPException(status_code=400, detail="帖子内容不能为空")
    _validate_images(images)

    # 敏感词过滤与消息域同源（core/sensitive），命中即拒绝
    hit = hit_sensitive(content)
    if hit:
        raise HTTPException(status_code=400, detail=f"内容包含敏感词：{hit}")

    post = Post(
        channel_id=conversation_id,
        author_id=current.id,
        content=content,
        images=images,
        card_user_id=card_author.id if card_author else None,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return _post_out(post, current, liked=False, card_author=card_author)


@router.get("/{conversation_id}/posts/{post_id}", response_model=PostOut)
async def post_detail(
    conversation_id: int,
    post_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """帖子详情：含 ``liked_by_me`` 与名片帖的被推荐用户信息。"""
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)
    post = await _post_or_404(db, conversation_id, post_id)

    author = await db.get(User, post.author_id)
    card_author = await db.get(User, post.card_user_id) if post.card_user_id else None
    liked = await _liked_ids(db, current.id, LIKE_POST, {post.id})
    return _post_out(post, author, post.id in liked, card_author)


@router.put("/{conversation_id}/posts/{post_id}", response_model=PostOut)
async def update_post(
    conversation_id: int,
    post_id: int,
    body: PostCreateIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """编辑帖子：仅限本人（IA：编辑帖子（本人））。

    校验口径与发帖一致（非空、配图、敏感词）；名片帖允许只保留名片而无正文。
    """
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)
    post = await _post_or_404(db, conversation_id, post_id)
    if post.author_id != current.id:
        raise HTTPException(status_code=403, detail="仅作者本人可编辑帖子")

    content = body.content.strip()
    images = [url.strip() for url in body.images if url and url.strip()]
    # 名片帖可只有名片；普通帖必须有正文或配图
    if not content and not images and post.card_user_id is None:
        raise HTTPException(status_code=400, detail="帖子内容不能为空")
    _validate_images(images)
    hit = hit_sensitive(content)
    if hit:
        raise HTTPException(status_code=400, detail=f"内容包含敏感词：{hit}")

    post.content = content
    post.images = images
    await db.commit()
    await db.refresh(post)

    card_author = await db.get(User, post.card_user_id) if post.card_user_id else None
    liked = await _liked_ids(db, current.id, LIKE_POST, {post.id})
    return _post_out(post, current, post.id in liked, card_author)


@router.delete("/{conversation_id}/posts/{post_id}")
async def delete_post(
    conversation_id: int,
    post_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除帖子：本人 / 频道管理 / 系统管理员（IA：删除帖子（本人 / 管理员））。软删。"""
    await _channel_or_404(db, conversation_id)
    member = await _assert_member(db, conversation_id, current.id)
    post = await _post_or_404(db, conversation_id, post_id)

    allowed = post.author_id == current.id or member.role in ("owner", "admin") or current.is_admin
    if not allowed:
        raise HTTPException(status_code=403, detail="仅作者或管理员可删除帖子")

    post.status = 0
    post.is_pinned = False
    # 软删留痕：status 只表达「是否已删除」，删除时间单独记录，便于事后追溯
    post.deleted_at = utcnow()
    await db.commit()
    return {"ok": True}


@router.post("/{conversation_id}/posts/{post_id}/pin")
async def pin_post(
    conversation_id: int,
    post_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """置顶帖子：仅频道主 / 管理员（IA：置顶 / 取消置顶（管理员））。

    与聊天消息的"唯一置顶"不同，帖子的置顶**不唯一**——
    帖子流按 ``is_pinned`` 优先排序，可同时置顶多条。
    """
    await _channel_or_404(db, conversation_id)
    await _require_role(db, conversation_id, current.id)
    post = await _post_or_404(db, conversation_id, post_id)

    post.is_pinned = True
    await db.commit()
    return {"ok": True}


@router.delete("/{conversation_id}/posts/{post_id}/pin")
async def unpin_post(
    conversation_id: int,
    post_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消帖子置顶：仅频道主 / 管理员。"""
    await _channel_or_404(db, conversation_id)
    await _require_role(db, conversation_id, current.id)
    post = await _post_or_404(db, conversation_id, post_id)

    post.is_pinned = False
    await db.commit()
    return {"ok": True}


# ---------- 评论 ----------

async def _comment_out(
    db: AsyncSession, comment: Comment, viewer_id: int, authors: dict[int, User]
) -> CommentOut:
    """组装评论响应。

    软删评论（status=0）作者置空、正文替换为 ``[该评论已删除]``，
    但仍保留在列表中占位——其下的回复要能定位到父评论；
    ``parent_author`` 供二级回复显示"回复 @某人"。
    """
    author = authors.get(comment.author_id) if comment.status == 1 else None
    parent_author = None
    if comment.parent_id:
        parent = await db.get(Comment, comment.parent_id)
        if parent is not None and parent.status == 1:
            parent_user = await db.get(User, parent.author_id)
            parent_author = parent_user.nickname if parent_user else None

    liked = await _liked_ids(db, viewer_id, LIKE_COMMENT, {comment.id})
    return CommentOut(
        id=comment.id,
        post_id=comment.post_id,
        author=(
            PostAuthorOut(
                user_id=author.id, nickname=author.nickname, avatar_url=author.avatar_url
            )
            if author
            else None
        ),
        parent_id=comment.parent_id,
        parent_author=parent_author,
        content=comment.content if comment.status == 1 else "[该评论已删除]",
        like_count=comment.like_count if comment.status == 1 else 0,
        liked_by_me=comment.status == 1 and comment.id in liked,
        created_at=comment.created_at,
    )


@router.get("/{conversation_id}/posts/{post_id}/comments", response_model=list[CommentOut])
async def comment_list(
    conversation_id: int,
    post_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """评论列表：两级结构扁平返回（前端按 ``parent_id`` 组树），按时间正序。

    软删评论保留占位，便于其下的回复仍能定位到父评论。
    """
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)
    await _post_or_404(db, conversation_id, post_id)

    rows = await db.execute(
        select(Comment)
        .where(Comment.post_id == post_id)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
    )
    comments = rows.scalars().all()
    authors = await _author_map(db, {c.author_id for c in comments})

    out = []
    for c in comments:
        out.append(await _comment_out(db, c, current.id, authors))
    return out


@router.post(
    "/{conversation_id}/posts/{post_id}/comments", response_model=CommentOut, status_code=201
)
async def create_comment(
    conversation_id: int,
    post_id: int,
    body: CommentCreateIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发表评论 / 回复。回复二级评论时自动归位到其一级父评论（最多两级）。"""
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)
    post = await _post_or_404(db, conversation_id, post_id)

    content = body.content.strip()
    hit = hit_sensitive(content)
    if hit:
        raise HTTPException(status_code=400, detail=f"评论包含敏感词：{hit}")

    parent_id = None
    if body.parent_id is not None:
        parent = await db.get(Comment, body.parent_id)
        if parent is None or parent.post_id != post_id or parent.status != 1:
            raise HTTPException(status_code=404, detail="被回复的评论不存在或已删除")
        # 二级评论下再回复 → 归位到它的一级父评论，保持两层结构
        parent_id = parent.parent_id or parent.id

    comment = Comment(
        post_id=post_id, author_id=current.id, parent_id=parent_id, content=content
    )
    db.add(comment)
    await db.execute(
        update(Post).where(Post.id == post_id).values(comment_count=Post.comment_count + 1)
    )
    await db.commit()
    await db.refresh(comment)
    return await _comment_out(db, comment, current.id, {current.id: current})


@router.delete("/{conversation_id}/comments/{comment_id}")
async def delete_comment(
    conversation_id: int,
    comment_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除评论：本人 / 频道管理 / 系统管理员。软删，其下回复保留。"""
    await _channel_or_404(db, conversation_id)
    member = await _assert_member(db, conversation_id, current.id)

    comment = await db.get(Comment, comment_id)
    if comment is None or comment.status != 1:
        raise HTTPException(status_code=404, detail="评论不存在或已删除")
    post = await _post_or_404(db, conversation_id, comment.post_id)

    allowed = (
        comment.author_id == current.id
        or member.role in ("owner", "admin")
        or current.is_admin
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="仅作者或管理员可删除评论")

    comment.status = 0
    # 软删留痕：同帖子，status 表达是否已删除，deleted_at 记删除时间
    comment.deleted_at = utcnow()
    await db.execute(
        update(Post).where(Post.id == post.id).values(comment_count=Post.comment_count - 1)
    )
    await db.commit()
    return {"ok": True}


# ---------- 点赞 ----------

# 下面四个端点（帖子 / 评论 × 点赞 / 取消）前置条件完全一致：
# 需为频道成员、目标存在且未删除；写操作幂等（重复调用结果一致），
# 并同步维护 post / comment 上的冗余计数 like_count（供热度排序使用）。
# 具体实现见 _add_like / _remove_like。

async def _add_like(db: AsyncSession, user_id: int, target_type: int, target_id: int) -> None:
    """点赞（幂等）：已点过则直接返回；同时原子递增目标表的 ``like_count``。"""
    exists = await db.scalar(
        select(Like).where(
            Like.user_id == user_id,
            Like.target_type == target_type,
            Like.target_id == target_id,
        )
    )
    if exists is not None:
        return  # 幂等：重复点赞直接视为成功

    db.add(Like(user_id=user_id, target_type=target_type, target_id=target_id))
    model = Post if target_type == LIKE_POST else Comment
    await db.execute(
        update(model).where(model.id == target_id).values(like_count=model.like_count + 1)
    )
    await db.commit()


async def _remove_like(db: AsyncSession, user_id: int, target_type: int, target_id: int) -> None:
    """取消点赞（幂等）：未点过则直接返回；同时原子递减 ``like_count``。"""
    like = await db.scalar(
        select(Like).where(
            Like.user_id == user_id,
            Like.target_type == target_type,
            Like.target_id == target_id,
        )
    )
    if like is None:
        return  # 幂等：未点赞时取消视为成功

    await db.delete(like)
    model = Post if target_type == LIKE_POST else Comment
    await db.execute(
        update(model).where(model.id == target_id).values(like_count=model.like_count - 1)
    )
    await db.commit()


@router.post("/{conversation_id}/posts/{post_id}/like")
async def like_post(
    conversation_id: int,
    post_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)
    await _post_or_404(db, conversation_id, post_id)
    await _add_like(db, current.id, LIKE_POST, post_id)
    return {"ok": True}


@router.delete("/{conversation_id}/posts/{post_id}/like")
async def unlike_post(
    conversation_id: int,
    post_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)
    await _post_or_404(db, conversation_id, post_id)
    await _remove_like(db, current.id, LIKE_POST, post_id)
    return {"ok": True}


@router.post("/{conversation_id}/comments/{comment_id}/like")
async def like_comment(
    conversation_id: int,
    comment_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)
    comment = await db.get(Comment, comment_id)
    if comment is None or comment.status != 1:
        raise HTTPException(status_code=404, detail="评论不存在或已删除")
    await _post_or_404(db, conversation_id, comment.post_id)
    await _add_like(db, current.id, LIKE_COMMENT, comment_id)
    return {"ok": True}


@router.delete("/{conversation_id}/comments/{comment_id}/like")
async def unlike_comment(
    conversation_id: int,
    comment_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _channel_or_404(db, conversation_id)
    await _assert_member(db, conversation_id, current.id)
    comment = await db.get(Comment, comment_id)
    if comment is None or comment.status != 1:
        raise HTTPException(status_code=404, detail="评论不存在或已删除")
    await _post_or_404(db, conversation_id, comment.post_id)
    await _remove_like(db, current.id, LIKE_COMMENT, comment_id)
    return {"ok": True}
