/* Fixed, non-Python E5-C supervisor, mount setup and synthetic fixtures.
 * Build explicitly as a static ELF; never compile/install during preparation.
 * No caller argv executor, source reader, runtime builder or networking target.
 * Linux x86_64 profile only. Guardian and supervisor stay outside payload cgroup.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/capability.h>
#include <linux/filter.h>
#include <linux/memfd.h>
#include <linux/seccomp.h>
#include <poll.h>
#include <sched.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>

#define MiB (1024UL * 1024UL)
#define MAX_OUTPUT 4096
static int requester_ready = -1;
static const char *names[] = {"isolation", "pids", "memory", "bytes", "inodes",
    "output", "deadline", "descendants", "setsid", "double_fork", "cancel",
    "requester_death", "supervisor_death"};

static int probe_index(const char *s) {
    for (unsigned i = 0; i < sizeof(names)/sizeof(names[0]); i++)
        if (!strcmp(s, names[i])) return (int)i;
    return !strcmp(s,"python_identity") ? 13 : -1;
}
static unsigned long number(const char *s, unsigned long lo, unsigned long hi) {
    char *end; errno = 0;
    unsigned long n = strtoul(s, &end, 10);
    if (errno || !*s || *end || n < lo || n > hi) _exit(90);
    return n;
}
static uint64_t monotonic_ms(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) _exit(90);
    return (uint64_t)t.tv_sec*1000 + (uint64_t)t.tv_nsec/1000000;
}
static void delay(void) { struct timespec t = {0, 10000000}; nanosleep(&t, NULL); }
static int write_all(int fd, const void *p, size_t n) {
    const char *s = p;
    while (n) {
        ssize_t k = write(fd, s, n);
        if (k < 0 && errno == EINTR) continue;
        if (k <= 0) return -1;
        s += k; n -= (size_t)k;
    }
    return 0;
}
static int control_write(int group, const char *key, const char *value) {
    int fd = openat(group, key, O_WRONLY|O_NOFOLLOW|O_CLOEXEC);
    if (fd < 0) return -1;
    int result = write_all(fd, value, strlen(value)); close(fd); return result;
}
static long counter(int group, const char *key, const char *label) {
    char data[2048];
    int fd = openat(group, key, O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = read(fd, data, sizeof(data)-1); close(fd);
    if (n < 0) return -1;
    data[n] = 0;
    if (!label) { char *end; long v = strtol(data, &end, 10); return end == data ? -1 : v; }
    char *save, *line = strtok_r(data, "\n", &save);
    while (line) {
        size_t z = strlen(label);
        if (!strncmp(line, label, z) && line[z] == ' ') return strtol(line+z+1, NULL, 10);
        line = strtok_r(NULL, "\n", &save);
    }
    return -1;
}
static int kill_empty(int group) {
    if (control_write(group, "cgroup.kill", "1\n")) return 0;
    uint64_t end = monotonic_ms()+2000;
    while (monotonic_ms() < end) {
        if (counter(group, "cgroup.events", "populated") == 0) return 1;
        delay();
    }
    return 0;
}
static void close_extra(void) {
    /* close_range, not a finite fd scan, is the production default-deny rule. */
    if (syscall(SYS_close_range, 3U, ~0U, 0U)) _exit(90);
}
static void sleep_fixture(void) {
    /* Finite even if all tested mechanisms unexpectedly fail. */
    struct timespec t = {10, 0}; nanosleep(&t, NULL); _exit(0);
}
static void restrict_syscalls(int identity) {
    struct __user_cap_header_struct h = {_LINUX_CAPABILITY_VERSION_3, 0};
    struct __user_cap_data_struct d[2] = {{0}, {0}};
    if (syscall(SYS_capset, &h, d) || prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) _exit(90);
    struct sock_filter f[] = {
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* Reject x32 syscall-number aliases too. */
        BPF_JUMP(BPF_JMP|BPF_JGE|BPF_K, 0x40000000, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
#define DENY(n) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, n, 0, 1), BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM)
        DENY(SYS_mount), DENY(SYS_umount2), DENY(SYS_unshare), DENY(SYS_setns),
        DENY(SYS_fsopen), DENY(SYS_fsmount), DENY(SYS_move_mount), DENY(SYS_open_tree),
        DENY(SYS_mount_setattr), DENY(SYS_clone3), DENY(SYS_ptrace), DENY(SYS_bpf),
        /* Only the fixed identity fixture needs an initial trusted execve.
         * It still has no caller code/argv API; all other closed probes deny it.
         * A second exec is rejected by the pointer-bound rule below. */
        DENY(SYS_execveat),
#undef DENY
        /* fork remains allowed; clone with ANY namespace flag is not. */
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_clone, 0, 3),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K,
            CLONE_NEWNS|CLONE_NEWCGROUP|CLONE_NEWUTS|CLONE_NEWIPC|CLONE_NEWUSER|CLONE_NEWPID|CLONE_NEWNET,
            0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW)
    };
    if (!identity) {
        struct sock_filter noexec[]={
            BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),
            BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,SYS_execve,0,1),
            BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM),
            BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)};
        struct sock_fprog noexecp={4,noexec};
        if (prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&noexecp)) _exit(90);
    }
    struct sock_fprog p = {(unsigned short)(sizeof(f)/sizeof(f[0])), f};
    if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &p)) _exit(90);
}
static int absent(const char *path) { struct stat s; return lstat(path, &s) < 0 && errno == ENOENT; }
static int denied_write(const char *path) {
    int fd = open(path, O_CREAT|O_WRONLY|O_CLOEXEC, 0600);
    if (fd >= 0) { close(fd); return 0; }
    return errno == EROFS || errno == EACCES || errno == ENOENT;
}
static void setup_fixture(int op, unsigned port) {
    const char *mounts[] = {"/work/venv", "/work/tmp", "/work/home"};
    const char *options[] = {"size=1048576,nr_inodes=32,mode=0700",
        "size=4096,nr_inodes=8,mode=0700", "size=4096,nr_inodes=8,mode=0700"};
    for (int i = 0; i < 3; i++) {
        if (mount("tmpfs", mounts[i], "tmpfs", MS_NOSUID|MS_NODEV|MS_NOEXEC, options[i])) _exit(91);
        struct statvfs v;
        if (statvfs(mounts[i], &v) || v.f_blocks*v.f_frsize != (i ? 4096UL : MiB)
            || v.f_files != (i ? 8UL : 32UL)) _exit(91);
    }
    /* Parent root, /proc and all non-scratch bindings are read-only. */
    if (mount(NULL, "/", NULL, MS_REMOUNT|MS_RDONLY|MS_NOSUID|MS_NODEV, NULL)) _exit(91);
    restrict_syscalls(op==13);
    /* Inspect actual descriptors after close_range. No socket/control FD is usable. */
    for (int fd = 0; fd < 1024; fd++) {
        struct stat s;
        if (!fstat(fd, &s) && (S_ISSOCK(s.st_mode) || fd > 2)) _exit(92);
    }
    if (op==13) {
        /* Fixed BoberAgent identity, no source/venv/packages, site or env input.
         * Bind this initial syscall's path pointer. After exec replaces the
         * address space, ordinary subsequent execve calls fail closed. This is
         * not a hostile-code executor or protection against a compromised,
         * operator-trusted interpreter recreating the same address. */
        static char loader[]="/runtime/bin/python3.12";
        uintptr_t address=(uintptr_t)loader;
        struct sock_filter once[]={
            BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),
            BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,SYS_execve,0,5),
            BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,args[0])),
            BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,(uint32_t)address,0,2),
            BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,args[0])+4),
            BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,(uint32_t)(address>>32),1,0),
            BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM),
            BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)};
        struct sock_fprog oncep={8,once};
        if (prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&oncep)) _exit(90);
        static char program[]=
            "import sys,os,json,sysconfig; "
            "print(json.dumps(dict(implementation=sys.implementation.name,"
            "version='.'.join(map(str,sys.version_info[:3])),platform=sys.platform,"
            "architecture=os.uname().machine,cache_tag=sys.implementation.cache_tag,"
            "soabi=sysconfig.get_config_var('SOABI'),prefix=sys.prefix,"
            "base_prefix=sys.base_prefix,executable=sys.executable,paths=sys.path,"
            "isolated=sys.flags.isolated,no_site=sys.flags.no_site,"
            "no_bytecode=sys.dont_write_bytecode),sort_keys=True,separators=(',',':')))";
        char *args[]={loader,"-I","-S","-B","-c",program,NULL};
        char *env[]={"LANG=C","HOME=/work/home","TMPDIR=/work/tmp",
            "LD_LIBRARY_PATH=/runtime/lib:/support",NULL};
        execve(loader,args,env); _exit(90);
    }
    if (op == 0) {
        const char *hidden[] = {"/etc/passwd", "/home", "/run", "/sys", "/dev/shm",
            "/run/docker.sock", "/run/containerd/containerd.sock", "/run/dbus/system_bus_socket",
            "/node-runtime", "/imported-inputs"};
        for (unsigned i=0; i < sizeof(hidden)/sizeof(hidden[0]); i++) if (!absent(hidden[i])) _exit(92);
        if (!denied_write("/outside") || !denied_write("/source/sentinel")) _exit(92);
        int sfd = open("/source/sentinel", O_RDONLY|O_NOFOLLOW);
        char s[16] = {0};
        if (sfd < 0 || read(sfd, s, sizeof(s)) != 10 || memcmp(s, "E5_SOURCE\n", 10)) _exit(92);
        close(sfd);
        if (!unshare(CLONE_NEWUSER) || !mount("tmpfs", "/work/venv", "tmpfs", 0, NULL)) _exit(92);
        int fd = socket(AF_INET, SOCK_STREAM|SOCK_CLOEXEC, 0);
        struct sockaddr_in a = {.sin_family=AF_INET, .sin_port=htons((uint16_t)port)};
        a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        if (fd < 0 || !connect(fd, (struct sockaddr*)&a, sizeof(a))) _exit(92);
        close(fd); puts("ISOLATION_PASS"); return;
    }
    if (op == 1) {
        int exhausted = 0;
        for (int i=0; i<16; i++) {
            pid_t p = fork();
            if (!p) sleep_fixture();
            if (p < 0) { exhausted = errno == EAGAIN; break; }
        }
        if (!exhausted) _exit(93);
        puts("PIDS_PASS"); fflush(stdout); sleep_fixture();
    }
    if (op == 2) {
        /* Bounded 96MiB touched allocation, never a memory bomb. */
        for (int i=0; i<96; i++) {
            volatile unsigned char *p = malloc(MiB);
            if (!p) _exit(94);
            for (unsigned j=0; j<MiB; j+=4096) p[j]=1;
        }
        _exit(94);
    }
    if (op == 3) {
        int fd = open("/work/venv/bytes", O_CREAT|O_WRONLY, 0600);
        char data[4096]; memset(data, 'x', sizeof(data));
        int blocked = 0;
        for (int i=0; i<512; i++) if (write(fd, data, sizeof(data)) < 0) { blocked = errno == ENOSPC; break; }
        if (fd >= 0) close(fd);
        if (!blocked) _exit(95);
        puts("BYTES_PASS"); return;
    }
    if (op == 4) {
        int blocked=0;
        for (int i=0; i<64; i++) {
            char path[64]; snprintf(path, sizeof(path), "/work/venv/inode-%d", i);
            int fd=open(path, O_CREAT|O_EXCL|O_WRONLY, 0600);
            if (fd<0) { blocked=errno==ENOSPC; break; } close(fd);
        }
        if (!blocked) _exit(95);
        puts("INODES_PASS"); return;
    }
    if (op == 5) {
        char data[4096]; memset(data, 'O', sizeof(data));
        for (int i=0; i<4; i++) { write_all(1, data, sizeof(data)); write_all(2, data, sizeof(data)); }
        sleep_fixture();
    }
    /* Deterministic descendant fixtures, not arbitrary workload execution. */
    if (op == 7 || op == 8 || op == 9 || op == 10 || op == 11 || op == 12) {
        int ready[2]; if (pipe2(ready,O_CLOEXEC)) _exit(96);
        pid_t p=fork(); if (p<0) _exit(96);
        if (!p) {
            close(ready[0]);
            if (op == 8 || op == 9) if (setsid()<0) _exit(96);
            pid_t q=fork(); if (q<0) _exit(96);
            if (!q) { close(ready[1]); sleep_fixture(); }
            if (write_all(ready[1],"R",1)) _exit(96);
            close(ready[1]);
            if (op == 9) _exit(0);
            sleep_fixture();
        }
        close(ready[1]);
        char established;
        if (read(ready[0],&established,1)!=1 || established!='R') _exit(96);
        close(ready[0]);
        puts("DESCENDANTS_STARTED"); fflush(stdout);
        if (op == 7 || op == 8 || op == 9) return;
    }
    sleep_fixture();
}

static void hex_print(const unsigned char *data, size_t n) {
    for (size_t i=0; i<n; i++) printf("%02x", data[i]);
}
/* Node-owned, bounded v2 descriptor. No whole lib bind, arbitrary bwrap options
 * or code/command selection. bwrap --args reads NUL arguments and closes its fd.
 * The payload still passes close_extra()/the fixed fixture's fd leak checks.
 */
static int argument_fd;
static size_t argument_bytes;
static unsigned argument_count;
static void projection_arg(const char *s) {
    size_t n=strlen(s)+1;
    if (++argument_count>8500 || n>8192 || argument_bytes+n>2*MiB
        || write_all(argument_fd,s,n)) _exit(90);
    argument_bytes+=n;
}
static void relative_path(const char *s) {
    if (!*s || strlen(s)>2048 || *s=='/' || s[strlen(s)-1]=='/') _exit(90);
    const char *p=s;
    while (*p) {
        size_t n=strcspn(p,"/");
        if (!n || n>255 || (n==1 && p[0]=='.') || (n==2 && !strncmp(p,"..",2))
            || strspn(p,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.+-")<n) _exit(90);
        p+=n; if (*p) p++;
    }
    if (strncmp(s,"bin/",4) && strcmp(s,"bin") && strncmp(s,"lib/",4)
        && strcmp(s,"lib") && strcmp(s,"PYTHON.json")) _exit(90);
}
static void relative_link(const char *path,const char *target) {
    if (!*target || *target=='/' || strlen(target)>2048 || target[strlen(target)-1]=='/') _exit(90);
    unsigned depth=0;
    for (const char *p=path;*p;p++) if (*p=='/') depth++;
    const char *p=target;
    while (*p) {
        size_t n=strcspn(p,"/");
        if (!n || n>255 || strspn(p,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.+-")<n) _exit(90);
        if (n==2 && !strncmp(p,"..",2)) { if (!depth) _exit(90); depth--; }
        else if (!(n==1 && *p=='.')) depth++;
        p+=n; if (*p) p++;
    }
    if (!depth) _exit(90);
}
static void projection_records(const char *file,const char *source) {
    int fd=open(file,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    struct stat before,after;
    if (fd<0 || fstat(fd,&before) || !S_ISREG(before.st_mode)
        || before.st_uid!=getuid() || (before.st_mode&07777)!=0600
        || before.st_size<1 || before.st_size>(long)MiB) _exit(90);
    size_t size=(size_t)before.st_size;
    char *data=malloc(size+1); if (!data) _exit(90);
    size_t used=0;
    while (used<size) { ssize_t n=read(fd,data+used,size-used); if (n<=0) _exit(90); used+=(size_t)n; }
    if (fstat(fd,&after) || before.st_ino!=after.st_ino || before.st_dev!=after.st_dev
        || before.st_size!=after.st_size || before.st_mode!=after.st_mode
        || before.st_uid!=after.st_uid || before.st_gid!=after.st_gid
        || before.st_mtim.tv_sec!=after.st_mtim.tv_sec || before.st_mtim.tv_nsec!=after.st_mtim.tv_nsec
        || before.st_ctim.tv_sec!=after.st_ctim.tv_sec || before.st_ctim.tv_nsec!=after.st_ctim.tv_nsec) _exit(90);
    close(fd); data[size]=0;
    if (strlen(data)!=size || data[size-1]!='\n') _exit(90);
    char *save=NULL,*line=strtok_r(data,"\n",&save);
    if (!line || strcmp(line,"m20-e5-python-projection-mounts@1")) _exit(90);
    line=strtok_r(NULL,"\n",&save);
    if (!line || strlen(line)!=64 || strspn(line,"0123456789abcdef")!=64) _exit(90);
    unsigned records=0;
    while ((line=strtok_r(NULL,"\n",&save))) {
        if (++records>2046) _exit(90);
        char *path=strchr(line,'\t'); if (!path) _exit(90); *path++=0;
        char *target=strchr(path,'\t'); if (!target) _exit(90); *target++=0;
        if (strchr(target,'\t')) _exit(90);
        relative_path(path);
        char from[4096],to[4096];
        if (snprintf(from,sizeof(from),"%s/%s",source,path)>=(int)sizeof(from)
            || snprintf(to,sizeof(to),"/runtime/%s",path)>=(int)sizeof(to)) _exit(90);
        if (!strcmp(line,"DIRECTORY") && !strcmp(target,"-")) {
            projection_arg("--dir");projection_arg(to);
        } else if (!strcmp(line,"BIND") && !strcmp(target,"-")) {
            projection_arg("--ro-bind");projection_arg(from);projection_arg(to);
        } else if (!strcmp(line,"SYMLINK")) {
            relative_link(path,target);
            projection_arg("--symlink");projection_arg(target);projection_arg(to);
        } else _exit(90);
    }
    if (!records) _exit(90);
    free(data);
}
static void supervisor(int argc, char **argv) {
    if (argc<9 || probe_index(argv[5]) < 0) _exit(90);
    const char *bwrap=argv[2], *helper=argv[3], *source=argv[4];
    int op=probe_index(argv[5]);
    if ((op!=13 && argc!=9) || (op==13 && (argc<12 || argc>43
        || strcmp(argv[9],"m20-e5-python-distribution@2")))) _exit(90);
    unsigned cap=(unsigned)number(argv[6], 6, 8);
    unsigned output=(unsigned)number(argv[7], 1024, MAX_OUTPUT);
    unsigned seconds=(unsigned)number(argv[8], 1, 3);
    int group=open(".", O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if (group<0 || counter(group, "pids.max", NULL)!=(long)cap
        || counter(group, "memory.max", NULL)!=64*(long)MiB
        || counter(group, "memory.swap.max", NULL)!=0
        || counter(group, "memory.oom.group", NULL)!=1) _exit(90);
    int life[2], gate[2], out[2], err[2], ready[2];
    if (pipe2(life, O_CLOEXEC) || pipe2(gate, O_CLOEXEC)
        || pipe2(out, O_CLOEXEC) || pipe2(err, O_CLOEXEC) || pipe2(ready,O_CLOEXEC)) _exit(90);
    uint64_t start=monotonic_ms(), deadline=start+seconds*1000;
    /* Guardian is independent of Node/request coroutine and supervisor lifetime.
     * It receives no payload output. EOF means supervisor death/normal teardown.
     * There is also a finite deadline in case a control fd was erroneously retained.
     */
    pid_t guardian=fork();
    if (guardian<0) _exit(90);
    if (!guardian) {
        if (requester_ready>=0) close(requester_ready);
        close(ready[0]);
        /* A process-group kill of the requester or supervisor must not also
         * kill their death watcher. No inherited terminal/session dependency. */
        if (setsid()<0 || !kill_empty(group)) _exit(97);
        if (write_all(ready[1],"R",1)) _exit(97);
        close(ready[1]);
        close(life[1]); close(gate[0]); close(gate[1]); close(out[0]); close(out[1]);
        close(err[0]); close(err[1]); close(0); close(1); close(2);
        struct pollfd p={life[0], POLLIN|POLLHUP, 0};
        while (monotonic_ms()<deadline+500) {
            if (poll(&p, 1, 20)>0) break;
        }
        int empty=kill_empty(group); close(life[0]); _exit(empty ? 0 : 97);
    }
    close(ready[1]);
    struct pollfd guard_ready={ready[0],POLLIN|POLLHUP,0};
    char established;
    if (poll(&guard_ready,1,500)<=0 || read(ready[0],&established,1)!=1 || established!='R') {
        close(life[1]); waitpid(guardian,NULL,0); _exit(97);
    }
    close(ready[0]);
    close(life[0]);
    pid_t parent=getpid();
    pid_t child=fork();
    if (child<0) { close(life[1]); waitpid(guardian, NULL, 0); _exit(90); }
    if (!child) {
        /* No fork-capable payload before this barrier; check death-registration race. */
        if (prctl(PR_SET_PDEATHSIG, SIGKILL) || getppid()!=parent) _exit(90);
        close(life[1]); close(gate[1]); close(out[0]); close(err[0]);
        char token;
        if (read(gate[0], &token, 1)!=1 || token!='G') _exit(90);
        if (dup2(out[1], 1)<0 || dup2(err[1], 2)<0) _exit(90);
        int null=open("/dev/null", O_RDONLY); if (null<0 || dup2(null,0)<0) _exit(90);
        close_extra();
        /* Static fixture only: no whole-/usr/root bind, no host user/control tree.
         * Retain just SYS_ADMIN for fixed mount setup, then drop before fixture.
         */
        char port[16]; snprintf(port, sizeof(port), "%s", getenv("E5_PROBE_PORT") ?: "1");
        char *args[]={(char*)bwrap, "--unshare-all", "--die-with-parent", "--new-session",
            "--clearenv", "--uid", "0", "--gid", "0",
            "--cap-drop", "ALL", "--cap-add", "CAP_SYS_ADMIN", "--proc", "/proc",
            "--remount-ro", "/proc", "--dir", "/work", "--dir", "/work/venv",
            "--dir", "/work/tmp", "--dir", "/work/home", "--dir", "/trusted",
            "--ro-bind", (char*)helper, "/trusted/helper", "--ro-bind", (char*)source, "/source",
            "--setenv", "HOME", "/work/home", "--setenv", "TMPDIR", "/work/tmp",
            "--chdir", "/work", "/trusted/helper", "fixture", op==13 ? "python_identity" : (char*)names[op], port, NULL};
        char *env[]={"PATH=/usr/bin:/bin", "LANG=C", NULL};
        if (op==13) {
            /* Paths are produced only by the Node's fully verified operator
             * distribution closure. No generic executable/code selection. */
            argument_fd=memfd_create("e5-identity-args",MFD_ALLOW_SEALING);
            if (argument_fd<0) _exit(90);
#define ARG(s) projection_arg(s)
            const char *base[]={bwrap,"--unshare-all","--die-with-parent","--new-session",
                "--clearenv","--uid","0","--gid","0","--cap-drop","ALL",
                "--cap-add","CAP_SYS_ADMIN","--proc","/proc","--remount-ro","/proc",
                "--dir","/work","--dir","/work/venv","--dir","/work/tmp","--dir",
                "/work/home","--dir","/trusted","--dir","/runtime","--dir","/support","--dir","/lib64",
                "--ro-bind",helper,"/trusted/helper"};
            for (unsigned j=1;j<sizeof(base)/sizeof(base[0]);j++) ARG(base[j]);
            projection_records(argv[10],source);
            char destinations[32][256];
            for (int j=11;j<argc;j++) {
                const char *name=strrchr(argv[j],'/');
                if (!name || !*++name || strlen(name)>128 || strspn(name,
                    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.+-")!=strlen(name)) _exit(90);
                snprintf(destinations[j-11],256,"/support/%s",name);
                ARG("--ro-bind");ARG(argv[j]);ARG(destinations[j-11]);
                if (!strcmp(name,"ld-linux-x86-64.so.2")) {
                    ARG("--ro-bind");ARG(argv[j]);ARG("/lib64/ld-linux-x86-64.so.2");
                }
            }
            ARG("--chdir");ARG("/work");ARG("/trusted/helper");
            ARG("identity-fixture");
#undef ARG
            if (lseek(argument_fd,0,SEEK_SET)<0 || fcntl(argument_fd,F_ADD_SEALS,
                F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL)) _exit(90);
            char fd_number[24];snprintf(fd_number,sizeof(fd_number),"%d",argument_fd);
            char *identity_args[]={(char*)bwrap,"--args",fd_number,NULL};
            execve(bwrap,identity_args,env); _exit(90);
        }
        execve(bwrap, args, env); _exit(90);
    }
    close(gate[0]); close(out[1]); close(err[1]);
    char pid[64]; snprintf(pid,sizeof(pid),"%d\n",child);
    int attached=!control_write(group,"cgroup.procs",pid)
        && counter(group,"cgroup.procs",NULL)==child;
    if (attached) {
        puts("ATTACHED"); fflush(stdout);
        write_all(gate[1],"G",1);
    }
    close(gate[1]);
    fcntl(out[0], F_SETFL, O_NONBLOCK); fcntl(err[0], F_SETFL, O_NONBLOCK);
    unsigned char stdout_data[MAX_OUTPUT], stderr_data[MAX_OUTPUT];
    size_t lengths[2]={0,0}; unsigned char *buffers[]={stdout_data,stderr_data};
    int status=0, exited=0, notified=0, open_streams[2]={1,1};
    const char *reason=attached ? "EXITED" : "START_FAILED";
    struct pollfd polls[]={{0,POLLIN|POLLHUP,0},{out[0],POLLIN|POLLHUP,0},{err[0],POLLIN|POLLHUP,0}};
    while (attached) {
        if (monotonic_ms()>=deadline) { reason="TIMEOUT"; break; }
        poll(polls,3,10);
        if (polls[0].revents) {
            char token; ssize_t n=read(0,&token,1);
            reason=n==1 && token=='C' ? "CANCELLED" : "OWNER_LOST"; break;
        }
        int overflow=0;
        for (int i=0;i<2;i++) if (open_streams[i]) {
            unsigned char data[1024]; ssize_t n=read(polls[i+1].fd,data,sizeof(data));
            if (n==0) open_streams[i]=0;
            if (n>0) {
                size_t free_bytes=output-lengths[0]-lengths[1];
                size_t keep=(size_t)n<free_bytes ? (size_t)n : free_bytes;
                memcpy(buffers[i]+lengths[i],data,keep); lengths[i]+=keep;
                if ((size_t)n>keep) overflow=1;
            }
        }
        if (overflow) { reason="OUTPUT"; break; }
        if (!notified && lengths[0]>=20 && !memcmp(stdout_data,"DESCENDANTS_STARTED\n",20)) {
            notified=1;
            if (op==10) { puts("DESCENDANTS_READY"); fflush(stdout); }
            if (op==11 && requester_ready>=0) {
                write_all(requester_ready,"R",1); close(requester_ready); requester_ready=-1;
            }
            if (op==12) {
                puts("SUPERVISOR_DEATH_READY");
                if (fflush(stdout)) _exit(90);
                kill(getpid(),SIGKILL);
            }
        }
        if (!exited && waitpid(child,&status,WNOHANG)==child) exited=1;
        if (exited && !open_streams[0] && !open_streams[1]) break;
    }
    int empty=kill_empty(group);
    if (!exited) waitpid(child,&status,0);
    close(out[0]); close(err[0]); close(life[1]);
    int guardian_status; waitpid(guardian,&guardian_status,0);
    if (!empty || !WIFEXITED(guardian_status) || WEXITSTATUS(guardian_status)) reason="CLEANUP_FAILED";
    long pids=counter(group,"pids.events","max"), oom=counter(group,"memory.events","oom_kill");
    long peak=counter(group,"memory.peak",NULL);
    if (pids<0 || oom<0 || peak<0) reason="START_FAILED";
    printf("{\"attached\":%s,\"empty\":%s,\"reason\":\"%s\",\"exit\":%d,"
        "\"pids\":%ld,\"oom\":%ld,\"memory_peak\":%ld,\"milliseconds\":%llu,\"stdout\":\"",
        attached?"true":"false",empty?"true":"false",reason,
        WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status),pids,oom,peak,
        (unsigned long long)(monotonic_ms()-start));
    hex_print(stdout_data,lengths[0]); printf("\",\"stderr\":\"");
    hex_print(stderr_data,lengths[1]); puts("\"}"); close(group);
    /* This supervisor owns the report independently of the requester it outlives.
     * The requester-mode fork returns through _exit(), NOT libc exit(): flush
     * the bounded final evidence explicitly or only ATTACHED reaches the Node.
     */
    if (fflush(stdout)) _exit(90);
}
int main(int argc,char **argv) {
    signal(SIGPIPE,SIG_IGN);
    if (argc==2 && !strcmp(argv[1],"--identity")) { puts("m20-e5-linux-bwrap-cgroup@1:static-helper-v1"); return 0; }
    if (argc>=2 && !strcmp(argv[1],"supervise")) { supervisor(argc,argv); return 0; }
    if (argc==9 && !strcmp(argv[1],"requester") && !strcmp(argv[5],"requester_death")) {
        int owner[2], ready[2];
        if (pipe2(owner,O_CLOEXEC) || pipe2(ready,O_CLOEXEC)) return 90;
        pid_t child=fork(); if (child<0) return 90;
        if (!child) {
            close(ready[0]); requester_ready=ready[1];
            close(owner[1]); if (dup2(owner[0],0)<0) _exit(90); close(owner[0]);
            argv[1]="supervise"; supervisor(argc,argv); _exit(0);
        }
        close(ready[1]);
        close(owner[0]);
        struct pollfd p={ready[0],POLLIN|POLLHUP,0}; char established;
        if (poll(&p,1,2500)>0 && read(ready[0],&established,1)==1 && established=='R')
            kill(getpid(),SIGKILL);
        close(ready[0]); close(owner[1]); waitpid(child,NULL,0); return 90;
    }
    if (argc==2 && !strcmp(argv[1],"identity-fixture")) { setup_fixture(13,1); return 0; }
    if (argc==4 && !strcmp(argv[1],"fixture") && probe_index(argv[2])>=0 && probe_index(argv[2])<13) {
        setup_fixture(probe_index(argv[2]),(unsigned)number(argv[3],1,65535)); return 0;
    }
    return 90;
}
