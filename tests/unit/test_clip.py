from pathlib import Path
from typing import Tuple

import clip
import numpy as np
import pytest
import torch
from clip_image import CLIPImageEncoderCUDA11
from jina import Document, DocumentArray, Executor
from PIL import Image

_EMBEDDING_DIM = 512


@pytest.fixture(scope="module")
def encoder() -> CLIPImageEncoderCUDA11:
    return CLIPImageEncoderCUDA11()


@pytest.fixture(scope="module")
def encoder_no_pre() -> CLIPImageEncoderCUDA11:
    return CLIPImageEncoderCUDA11(use_default_preprocessing=False)


@pytest.fixture(scope="function")
def nested_docs() -> DocumentArray:
    tensor = np.ones((224, 224, 3), dtype=np.uint8)
    docs = DocumentArray([Document(id="root1", tensor=tensor)])
    docs[0].chunks = [
        Document(id="chunk11", tensor=tensor),
        Document(id="chunk12", tensor=tensor),
        Document(id="chunk13", tensor=tensor),
    ]
    docs[0].chunks[0].chunks = [
        Document(id="chunk111", tensor=tensor),
        Document(id="chunk112", tensor=tensor),
    ]

    return docs


def test_config():
    ex = Executor.load_config(str(Path(__file__).parents[2] / 'config.yml'))
    assert ex.batch_size == 32


def test_no_documents(encoder: CLIPImageEncoderCUDA11):
    docs = DocumentArray()
    encoder.encode(docs=docs, parameters={})
    assert len(docs) == 0  # SUCCESS

def test_docs_no_tensors(encoder: CLIPImageEncoderCUDA11):
    docs = DocumentArray([Document()])
    encoder.encode(docs=DocumentArray(), parameters={})
    assert len(docs) == 1
    assert docs[0].embedding is None


def test_single_image(encoder: CLIPImageEncoderCUDA11):
    docs = DocumentArray([Document(tensor=np.ones((100, 100, 3), dtype=np.uint8))])
    encoder.encode(docs, {})

    assert docs[0].embedding.shape == (_EMBEDDING_DIM,)
    assert docs[0].embedding.dtype == np.float32


def test_single_image_no_preprocessing(encoder_no_pre: CLIPImageEncoderCUDA11):
    docs = DocumentArray([Document(tensor=np.ones((3, 224, 224), dtype=np.uint8))])
    encoder_no_pre.encode(docs, {})

    assert docs[0].embedding.shape == (_EMBEDDING_DIM,)
    assert docs[0].embedding.dtype == np.float32


def test_encoding_cpu():
    encoder = CLIPImageEncoderCUDA11(device="cpu")
    input_data = DocumentArray([Document(tensor=np.ones((100, 100, 3), dtype=np.uint8))])

    encoder.encode(docs=input_data, parameters={})

    assert input_data[0].embedding.shape == (_EMBEDDING_DIM,)


def test_cpu_no_preprocessing():
    encoder = CLIPImageEncoderCUDA11(device="cpu", use_default_preprocessing=False)
    input_data = DocumentArray([Document(tensor=np.ones((3, 224, 224), dtype=np.uint8))])

    encoder.encode(docs=input_data, parameters={})

    assert input_data[0].embedding.shape == (_EMBEDDING_DIM,)


@pytest.mark.gpu
def test_encoding_gpu():
    encoder = CLIPImageEncoderCUDA11(device="cuda")
    input_data = DocumentArray([Document(tensor=np.ones((100, 100, 3), dtype=np.uint8))])

    encoder.encode(docs=input_data, parameters={})

    assert input_data[0].embedding.shape == (_EMBEDDING_DIM,)


@pytest.mark.gpu
def test_gpu_no_preprocessing():
    encoder = CLIPImageEncoderCUDA11(device="cuda", use_default_preprocessing=False)
    input_data = DocumentArray(
        [Document(tensor=np.ones((3, 224, 224), dtype=np.float32))]
    )

    encoder.encode(docs=input_data, parameters={})

    assert input_data[0].embedding.shape == (_EMBEDDING_DIM,)


def test_clip_any_image_shape(encoder: CLIPImageEncoderCUDA11):
    docs = DocumentArray([Document(tensor=np.ones((224, 224, 3), dtype=np.uint8))])

    encoder.encode(docs=docs, parameters={})
    assert len(docs.embeddings) == 1

    docs = DocumentArray([Document(tensor=np.ones((100, 100, 3), dtype=np.uint8))])
    encoder.encode(docs=docs, parameters={})
    assert len(docs.embeddings) == 1


def test_clip_batch(encoder: CLIPImageEncoderCUDA11):
    """
    This tests that the encoder can handle inputs of various size
    which is not a factorial of ``default_batch_size``

    """
    docs = DocumentArray(
        [
            Document(tensor=np.ones((100, 100, 3), dtype=np.uint8)),
            Document(tensor=np.ones((100, 100, 3), dtype=np.uint8)),
        ]
    )
    encoder.encode(docs, parameters={})
    assert len(docs.embeddings) == 2
    assert docs[0].embedding.shape == (_EMBEDDING_DIM,)
    assert docs[0].embedding.dtype == np.float32
    np.testing.assert_allclose(docs[0].embedding, docs[1].embedding)


def test_batch_no_preprocessing(encoder_no_pre: CLIPImageEncoderCUDA11):
    docs = DocumentArray(
        [
            Document(tensor=np.ones((3, 224, 224), dtype=np.float32)),
            Document(tensor=np.ones((3, 224, 224), dtype=np.float32)),
        ]
    )
    encoder_no_pre.encode(docs, {})
    assert len(docs.embeddings) == 2
    assert docs[0].embedding.shape == (_EMBEDDING_DIM,)
    assert docs[0].embedding.dtype == np.float32
    np.testing.assert_allclose(docs[0].embedding, docs[1].embedding)


@pytest.mark.parametrize("batch_size", [1, 2, 4, 8])
def test_batch_size(encoder: CLIPImageEncoderCUDA11, batch_size: int):
    tensor = np.ones((100, 100, 3), dtype=np.uint8)
    docs = DocumentArray([Document(tensor=tensor) for _ in range(32)])
    encoder.encode(docs, parameters={"batch_size": batch_size})

    for doc in docs:
        assert doc.embedding.shape == (_EMBEDDING_DIM,)


@pytest.mark.parametrize("batch_size", [1, 2, 4, 8])
def test_batch_size_no_preprocessing(encoder_no_pre: CLIPImageEncoderCUDA11, batch_size: int):
    tensor = np.ones((3, 224, 224), dtype=np.uint8)
    docs = DocumentArray([Document(tensor=tensor) for _ in range(32)])
    encoder_no_pre.encode(docs, parameters={"batch_size": batch_size})

    for doc in docs:
        assert doc.embedding.shape == (_EMBEDDING_DIM,)


def test_embeddings_quality(encoder: CLIPImageEncoderCUDA11):
    """
    This tests that the embeddings actually "make sense".
    We check this by making sure that the distance between the embeddings
    of two similar images is smaller than everything else.
    """

    data_dir = Path(__file__).parent.parent / "imgs"
    dog = Document(id="dog", tensor=np.array(Image.open(data_dir / "dog.jpg")))
    cat = Document(id="cat", tensor=np.array(Image.open(data_dir / "cat.jpg")))
    airplane = Document(
        id="airplane", tensor=np.array(Image.open(data_dir / "airplane.jpg"))
    )
    helicopter = Document(
        id="helicopter", tensor=np.array(Image.open(data_dir / "helicopter.jpg"))
    )

    docs = DocumentArray([dog, cat, airplane, helicopter])
    encoder.encode(docs, {})

    docs.match(docs)
    matches = ["cat", "dog", "helicopter", "airplane"]
    for i, doc in enumerate(docs):
        assert doc.matches[1].id == matches[i]


def test_openai_embed_match():
    data_dir = Path(__file__).parent.parent / "imgs"
    dog = Document(id="dog", tensor=np.array(Image.open(data_dir / "dog.jpg")))
    airplane = Document(
        id="airplane", tensor=np.array(Image.open(data_dir / "airplane.jpg"))
    )
    helicopter = Document(
        id="helicopter", tensor=np.array(Image.open(data_dir / "helicopter.jpg"))
    )

    docs = DocumentArray([dog, airplane, helicopter])

    clip_text_encoder = CLIPImageEncoderCUDA11("openai/clip-vit-base-patch32", device="cpu")
    clip_text_encoder.encode(docs, {})

    actual_embedding = np.stack(docs.embeddings)

    # assert same results with OpenAI's implementation
    model, preprocess = clip.load("ViT-B/32", device="cpu")
    tensors = [doc.tensor for doc in docs]

    with torch.no_grad():
        images = [Image.fromarray(tensor) for tensor in tensors]
        tensors = [preprocess(img) for img in images]
        tensor = torch.stack(tensors)
        expected_embedding = model.encode_image(tensor).numpy()

    np.testing.assert_almost_equal(actual_embedding, expected_embedding, 5)


@pytest.mark.parametrize(
    "traversal_paths, counts",
    [
        ['@c', (('@r', 0), ('@c', 3), ('@cc', 0))],
        ['@cc', (('@r', 0), ('@c', 0), ('@cc', 2))],
        ['@r', (('@r', 1), ('@c', 0), ('@cc', 0))],
        ['@cc,r', (('@r', 1), ('@c', 0), ('@cc', 2))],
    ],
)
def test_traversal_path(
    traversal_paths: str,
    counts: Tuple[str, int],
    nested_docs: DocumentArray,
    encoder: CLIPImageEncoderCUDA11,
):
    encoder.encode(nested_docs, parameters={"traversal_paths": traversal_paths})
    for path, count in counts:
        embeddings = nested_docs[path].embeddings
        if count != 0:
            assert len([em for em in embeddings if em is not None]) == count
        else:
            assert embeddings is None

