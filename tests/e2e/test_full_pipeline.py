def test_ingest_and_query_roundtrip(container, loop) -> None:  # noqa: ANN001
    payload = (
        "Decidimos usar guard clauses em todas as validações de entrada. "
        "Isso reduz complexidade ciclomática e melhora manutenção."
    )
    ingest = loop.run_until_complete(
        container.agent_loop.post_task_summary(
            task_description="Padronizar validações de entrada",
            changes=payload,
            project="CORE",
        )
    )
    assert ingest["candidates_extracted"] >= 1

    results = loop.run_until_complete(
        container.search.search(
            query_text="guard clauses validation input",
            project="CORE",
            top_k=5,
        )
    )
    assert isinstance(results, list)
