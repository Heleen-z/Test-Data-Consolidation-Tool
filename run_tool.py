from multiprocessing import freeze_support


if __name__ == "__main__":
    freeze_support()
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--bridge-self-test":
        from testdata_tool.bridge_diagnostics import write_self_test
        raise SystemExit(write_self_test(sys.argv[2]))
    from testdata_tool.launcher import main
    main()
