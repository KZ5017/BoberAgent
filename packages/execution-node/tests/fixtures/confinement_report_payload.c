/* TEST ONLY: real finite descendants, simulated cgroup control files.
 * Not bubblewrap, kernel enforcement, an executable provider, or acceptance.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopped;
static void stop(int signal_number) { (void)signal_number; stopped = 1; }
static void delay(void) { struct timespec t = {0, 1000000}; nanosleep(&t, NULL); }
static void finite_wait(void) {
    for (unsigned i = 0; i < 6000 && !stopped; ++i) delay();
}
static void reap(pid_t child) {
    kill(child, SIGTERM);
    while (waitpid(child, NULL, 0) < 0 && errno == EINTR) {}
}
int main(void) {
    /* Simulated kernel monitor, not PDEATHSIG, cleans this test-owned tree. */
    if (prctl(PR_SET_PDEATHSIG, 0)) return 90;
    signal(SIGTERM, stop);
    int ready[2];
    if (pipe(ready)) return 90;
    pid_t child = fork();
    if (child < 0) return 90;
    if (!child) {
        close(ready[0]);
        pid_t grandchild = fork();
        if (grandchild < 0) _exit(90);
        if (!grandchild) { close(ready[1]); finite_wait(); _exit(0); }
        if (write(ready[1], &grandchild, sizeof(grandchild)) != sizeof(grandchild)) _exit(90);
        close(ready[1]); finite_wait(); reap(grandchild); _exit(0);
    }
    close(ready[1]);
    pid_t grandchild;
    if (read(ready[0], &grandchild, sizeof(grandchild)) != sizeof(grandchild)) {
        reap(child); return 90;
    }
    close(ready[0]);
    FILE *file = fopen("test-descendants", "w");
    if (!file) { reap(child); return 90; }
    fprintf(file, "%d %d %d %d\n", getpid(), getppid(), child, grandchild);
    fclose(file);
    for (unsigned i = 0; i < 6000 && !stopped && access("test-start", F_OK); ++i) delay();
    if (!stopped && !access("test-start", F_OK)) {
        puts("DESCENDANTS_STARTED"); fflush(stdout);
    }
    finite_wait(); reap(child); return 0;
}
