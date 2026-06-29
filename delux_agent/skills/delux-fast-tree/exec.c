#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

#define MAX_ENTRIES    500
#define MAX_INO_TRACK  4096
#define NAME_TRUNCATE  120
#define PATH_MAX_       4096

typedef struct {
    char         display[256];
    char         realname[256];
    unsigned char is_dir;
} Entry;

typedef struct {
    dev_t dev;
    ino_t ino;
} InodeKey;

static int          g_json      = 0;
static int          g_max_depth = 5;
static int          g_total_entries = 0;
static int          g_dir_count  = 0;
static int          g_file_count = 0;
static InodeKey     g_visited[MAX_INO_TRACK];
static int          g_visited_count = 0;
static int          first_entry = 1;

static int inode_seen(dev_t dev, ino_t ino) {
    for (int i = 0; i < g_visited_count; i++) {
        if (g_visited[i].dev == dev && g_visited[i].ino == ino) return 1;
    }
    if (g_visited_count < MAX_INO_TRACK) {
        g_visited[g_visited_count].dev = dev;
        g_visited[g_visited_count].ino = ino;
        g_visited_count++;
    }
    return 0;
}

static int entry_cmp(const void *a, const void *b) {
    const Entry *ea = (const Entry *)a;
    const Entry *eb = (const Entry *)b;
    if (ea->is_dir != eb->is_dir) return eb->is_dir - ea->is_dir;
    return strcmp(ea->display, eb->display);
}

static void json_print_name(const char *s) {
    for (; *s; s++) {
        switch (*s) {
            case '"':  printf("\\\""); break;
            case '\\': printf("\\\\"); break;
            case '\n': printf("\\n");  break;
            case '\r': printf("\\r");  break;
            case '\t': printf("\\t");  break;
            default:   putchar(*s);    break;
        }
    }
}

static void print_json_entry(const Entry *e, int depth) {
    if (!first_entry) printf(",");
    first_entry = 0;
    printf("{\"name\":\"");
    json_print_name(e->display);
    printf("\",\"type\":\"%s\",\"depth\":%d}", e->is_dir ? "dir" : "file", depth);
}

static void print_tree(const char *path, int depth) {
    if (g_total_entries >= MAX_ENTRIES || depth > g_max_depth) return;

    DIR *dir = opendir(path);
    if (!dir) {
        if (!g_json) {
            for (int j = 0; j < depth; j++) printf("│   ");
            printf("  \033[1;31m[%s]\033[0m\n", strerror(errno));
        }
        return;
    }

    Entry entries[MAX_ENTRIES];
    int count = 0;

    struct dirent *de;
    while ((de = readdir(dir)) != NULL && g_total_entries < MAX_ENTRIES) {
        const char *nm = de->d_name;
        if (strcmp(nm, ".") == 0 || strcmp(nm, "..") == 0) continue;
        if (nm[0] == '.') continue;
        if (strcmp(nm, "node_modules") == 0) continue;
        if (strcmp(nm, "__pycache__") == 0) continue;
        if (strcmp(nm, "venv") == 0) continue;
        if (strcmp(nm, "dist") == 0) continue;
        if (strcmp(nm, "build") == 0) continue;
        if (strcmp(nm, "target") == 0) continue;

        /* build full path for stat */
        char full[PATH_MAX_];
        snprintf(full, sizeof(full), "%s/%s", path, nm);

        struct stat lst;
        if (lstat(full, &lst) != 0) continue;

        if (S_ISLNK(lst.st_mode)) {
            struct stat rst;
            if (stat(full, &rst) != 0) continue;
            if (!S_ISDIR(rst.st_mode)) continue; /* skip symlinks to files */
            if (inode_seen(rst.st_dev, rst.st_ino)) continue;
            entries[count].is_dir = 1;
        } else if (S_ISDIR(lst.st_mode)) {
            if (inode_seen(lst.st_dev, lst.st_ino)) continue;
            entries[count].is_dir = 1;
        } else {
            entries[count].is_dir = 0;
        }

        /* store real name for filesystem traversal */
        strncpy(entries[count].realname, nm, sizeof(entries[count].realname) - 1);
        entries[count].realname[sizeof(entries[count].realname) - 1] = '\0';

        /* store display name (possibly truncated) */
        size_t nlen = strlen(nm);
        if (nlen > NAME_TRUNCATE) {
            memcpy(entries[count].display, nm, NAME_TRUNCATE);
            strcpy(entries[count].display + NAME_TRUNCATE, "...");
        } else {
            strcpy(entries[count].display, nm);
        }

        count++;
    }
    closedir(dir);

    qsort(entries, count, sizeof(Entry), entry_cmp);

    for (int i = 0; i < count && g_total_entries < MAX_ENTRIES; i++) {
        g_total_entries++;
        if (entries[i].is_dir) g_dir_count++; else g_file_count++;

        if (g_json) {
            print_json_entry(&entries[i], depth);
        } else {
            for (int j = 0; j < depth; j++) printf("│   ");
            int last = (i == count - 1);
            printf("%s── ", last ? "└" : "├");
            if (entries[i].is_dir)
                printf("\033[1;34m%s/\033[0m\n", entries[i].display);
            else
                printf("%s\n", entries[i].display);
        }

        if (entries[i].is_dir && depth < g_max_depth && g_total_entries < MAX_ENTRIES) {
            char full[PATH_MAX_];
            snprintf(full, sizeof(full), "%s/%s", path, entries[i].realname);
            print_tree(full, depth + 1);
        }
    }

    if (count == 0 && !g_json) {
        for (int j = 0; j < depth; j++) printf("│   ");
        printf("  \033[2m(empty)\033[0m\n");
    }
}

int main(int argc, char *argv[]) {
    const char *root = ".";

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--json") == 0) {
            g_json = 1;
        } else if (strcmp(argv[i], "--depth") == 0 && i + 1 < argc) {
            g_max_depth = atoi(argv[++i]);
            if (g_max_depth < 1) g_max_depth = 1;
            if (g_max_depth > 20) g_max_depth = 20;
        } else if (argv[i][0] != '-') {
            root = argv[i];
        }
    }

    struct stat rst;
    if (stat(root, &rst) == 0 && S_ISDIR(rst.st_mode))
        inode_seen(rst.st_dev, rst.st_ino);

    if (g_json) {
        printf("{\"status\":\"ok\",\"data\":{");
        printf("\"root\":\"");
        json_print_name(root);
        printf("\",\"max_depth\":%d,\"entries\":[", g_max_depth);
        print_tree(root, 0);
        printf("],\"dirs\":%d,\"files\":%d,\"truncated\":%s}}\n",
               g_dir_count, g_file_count,
               g_total_entries >= MAX_ENTRIES ? "true" : "false");
    } else {
        printf("\033[1;36m%s (Project Root)\033[0m\n", root);
        print_tree(root, 0);
        printf("\n\033[2m%dd  %df\033[0m", g_dir_count, g_file_count);
        if (g_total_entries >= MAX_ENTRIES)
            printf("  \033[1;33m[truncated at %d entries]\033[0m", MAX_ENTRIES);
        printf("\n");
    }

    return 0;
}
