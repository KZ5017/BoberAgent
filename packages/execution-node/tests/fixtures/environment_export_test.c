/* Portable test of production export framing/sealing, NOT confinement proof. */
#define main production_main
#include "../../src/boberagent_execution_node/preparation/native/e5_confinement.c"
#undef main

int main(int argc, char **argv) {
    if (argc != 2) return 99;
    int source = memfd_create("test-export", MFD_ALLOW_SEALING);
    int sink[2], life[2];
    if (source < 0 || pipe(sink) || pipe(life) || dup2(life[0], 0) < 0) return 99;
    const char bytes[] = "bounded-fixture";
    if (write_all(source, bytes, sizeof(bytes))) return 99;
    uint64_t deadline = monotonic_ms() + 1000;
    if (!strcmp(argv[1], "oversize")) {
        if (ftruncate(source, ENVIRONMENT_EXPORT_MAX + 1)) return 99;
    } else if (!strcmp(argv[1], "short")) {
        if (ftruncate(source, 3)) return 99;
    } else if (!strcmp(argv[1], "expired")) deadline = monotonic_ms();
    else if (!strcmp(argv[1], "owner-lost")) close(life[1]);
    else if (!strcmp(argv[1], "wrong-sink")) {
        close(sink[1]); sink[1] = memfd_create("wrong-sink", MFD_ALLOW_SEALING);
    } else if (strcmp(argv[1], "success")) return 99;
    int accepted = export_environment(source, sink[1], deadline);
    if (strcmp(argv[1], "success")) return accepted ? 1 : 0;
    if (!accepted || write(source, "x", 1) >= 0 || errno != EPERM) return 2;
    char received[sizeof(bytes)];
    if (read(sink[0], received, sizeof(received)) != sizeof(received)
        || memcmp(bytes, received, sizeof(bytes))) return 3;
    return 0;
}
