/* Invoke actual production mount setup, stopping at the fixed Python exec.
 * Mechanical capacity check only: not provenance/cgroup/readiness acceptance. */
#define execve capacity_execve
#define main production_main
#include "../../src/boberagent_execution_node/preparation/native/e5_confinement.c"
#undef main
#undef execve

int capacity_execve(const char *file,char *const argv[],char *const env[]) {
    (void)env;
    if (strcmp(file,"/runtime/bin/python3.12") || strcmp(argv[4],"/trusted/environment.py")
        || strcmp(argv[5],"create")) _exit(99);
    struct statvfs v;
    struct rlimit limit;
    if (statvfs("/work/venv",&v) || v.f_blocks*v.f_frsize!=ENVIRONMENT_SCRATCH_MAX
        || v.f_files!=ENVIRONMENT_INODES || getrlimit(RLIMIT_FSIZE,&limit)
        || limit.rlim_cur!=ENVIRONMENT_EXPORT_MAX) _exit(99);
    /* Materialize allocated pages, not merely a sparse apparent size. No host
     * write: production setup mounted this private sized/inode-bounded tmpfs. */
    int fd=open("/work/venv/capacity",O_RDWR|O_CREAT|O_EXCL|O_CLOEXEC,0600);
    if (fd<0 || fallocate(fd,0,0,ENVIRONMENT_WRITE_MAX)) _exit(99);
    struct stat s;
    if (fstat(fd,&s) || (uint64_t)s.st_size!=ENVIRONMENT_WRITE_MAX
        || (uint64_t)s.st_blocks*512<ENVIRONMENT_WRITE_MAX) _exit(99);
    close(fd);
    printf("%lu %lu %lu\n",ENVIRONMENT_WRITE_MAX,ENVIRONMENT_SCRATCH_MAX,ENVIRONMENT_INODES);
    _exit(fflush(stdout) ? 99 : 0);
}

int main(int argc,char **argv) {
    if (argc==2 && !strcmp(argv[1],"scratch-child")) {
        setup_fixture(14,1); return 99;
    }
    if (argc!=2) return 99;
    int source=memfd_create("fixed-export",MFD_ALLOW_SEALING|MFD_CLOEXEC);
    if (source<0) return 99;
    prepare_environment_export(source);
    char *args[]={argv[1],"--unshare-all","--die-with-parent","--new-session",
        "--uid","0","--gid","0","--cap-drop","ALL","--cap-add","CAP_SYS_ADMIN",
        "--proc","/proc","--remount-ro","/proc","--dir","/work",
        "--dir","/work/venv","--dir","/work/tmp","--dir","/work/home",
        "--dir","/trusted","--ro-bind",argv[0],"/trusted/helper","--",
        "/trusted/helper","scratch-child",NULL};
    execv(argv[1],args); return 99;
}
