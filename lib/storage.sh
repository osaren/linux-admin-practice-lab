#!/usr/bin/env bash
set -euo pipefail

DIR=/var/lib/lfcs-disks
RUN=/run/lfcs-lab
MOUNTS=(
  /mnt/lfcs/data /mnt/lfcs/xfs /mnt/lfcs/lvm /mnt/lfcs/swap
  /mnt/lfcs/nfs /mnt/lfcs/sshfs /mnt/lfcs/nbd
  /mnt/lfcs/orchard /mnt/lfcs/crates /mnt/lfcs/garden
  /mnt/lfcs/observatory /mnt/lfcs/noexec /mnt/lfcs/archive
  /mnt/lfcs/recovery /mnt/lfcs/projects /mnt/lfcs/amber
  /mnt/lfcs/remote
)
LAB_VGS=(lfcs_vg lfcs_extend lfcs_xfs orchard oldfruit freshfruit garden observatory)

[[ -x /usr/local/lib/lfcs/verify-guest.py ]] && /usr/local/lib/lfcs/verify-guest.py || {
  echo 'LFCS storage: candidate guest marker missing; refusing privileged reset' >&2; exit 1;
}

owned_loop() {
  local loop=$1 n backing
  [[ $loop =~ ^/dev/loop[0-9]+$ ]] || return 1
  backing=$(losetup -n -O BACK-FILE "$loop" 2>/dev/null | head -1)
  for n in 1 2 3; do
    [[ $backing == "$DIR/disk${n}.img" ]] && return 0
  done
  return 1
}

check_owned_disk_paths() {
  local n file link loop
  [[ ! -L $DIR ]] || { echo 'LFCS storage: disk directory is a symlink' >&2; return 1; }
  for n in 1 2 3; do
    file="$DIR/disk${n}.img"
    link="/dev/lfcs-disk${n}"
    [[ ! -L $file ]] || { echo "LFCS storage: symlinked disk image $file; preserved" >&2; return 1; }
    if [[ -e $link || -L $link ]]; then
      [[ -L $link ]] || { echo "LFCS storage: unowned device $link; preserved" >&2; return 1; }
      loop=$(readlink -f "$link" 2>/dev/null || true)
      owned_loop "$loop" || { echo "LFCS storage: unowned link $link; preserved" >&2; return 1; }
    fi
  done
}

unmount_lab_paths() {
  local mp
  for mp in "${MOUNTS[@]}"; do
    timeout 5s umount -R "$mp" 2>/dev/null || true
    mountpoint -q "$mp" 2>/dev/null && umount -l "$mp" 2>/dev/null || true
  done
}

disk_candidates() {
  local n=$1 file link loop
  file="$DIR/disk${n}.img"
  link="/dev/lfcs-disk${n}"
  if [[ -L $link ]]; then
    loop=$(readlink -f "$link" 2>/dev/null || true)
    owned_loop "$loop" && printf '%s\n' "$loop"
  fi
  losetup -j "$file" 2>/dev/null | cut -d: -f1 | while read -r loop; do
    owned_loop "$loop" && printf '%s\n' "$loop"
  done
}

swapoff_disk_tree() {
  local loop=$1 source real node
  while read -r source; do
    [[ -n $source ]] || continue
    real=$(readlink -f "$source" 2>/dev/null || true)
    while read -r node; do
      [[ $real == "$(readlink -f "$node" 2>/dev/null || true)" ]] || continue
      swapoff "$source"
      break
    done < <(lsblk -nrpo NAME "$loop" 2>/dev/null)
  done < <(swapon --noheadings --raw --show=NAME 2>/dev/null || true)
}

unmount_disk_tree() {
  local loop=$1 mp
  while read -r mp; do
    [[ $mp == /* ]] || continue
    timeout 5s umount "$mp" 2>/dev/null || umount -l "$mp"
  done < <(lsblk -nrpo MOUNTPOINT "$loop" 2>/dev/null | awk 'NF' | sort -r)
}

remove_lab_vgs() {
  local vg pv loop seen
  for vg in "${LAB_VGS[@]}"; do
    vgs "$vg" >/dev/null 2>&1 || continue
    seen=0
    while read -r pv; do
      [[ -n $pv ]] || continue
      seen=1
      pv=$(readlink -f "$pv") || return 1
      loop=$(lsblk -no PKNAME "$pv" 2>/dev/null | head -1)
      [[ -n $loop ]] || loop=$(basename "$pv")
      [[ $loop == loop[0-9]* ]] || { echo "LFCS storage: $vg has an unowned PV $pv" >&2; return 1; }
      owned_loop "/dev/$loop" || { echo "LFCS storage: $vg has an unowned PV $pv" >&2; return 1; }
    done < <(pvs --noheadings -o pv_name --select "vg_name=$vg" 2>/dev/null | xargs -n1)
    [[ $seen == 1 ]] || { echo "LFCS storage: cannot establish PV ownership for $vg" >&2; return 1; }
    vgchange -an "$vg" >/dev/null 2>&1 || true
    vgremove -ff -y "$vg" >/dev/null
  done
  pvscan --cache >/dev/null 2>&1 || true
  dmsetup mknodes >/dev/null 2>&1 || true
}

detach_loop() {
  local loop=$1 n
  losetup "$loop" >/dev/null 2>&1 || return 0
  swapoff_disk_tree "$loop"
  unmount_disk_tree "$loop"
  partx -d "$loop" >/dev/null 2>&1 || true
  blockdev --flushbufs "$loop" >/dev/null 2>&1 || true
  udevadm settle
  losetup -d "$loop"
  for n in {1..100}; do
    losetup "$loop" >/dev/null 2>&1 || break
    udevadm settle
    sleep 0.02
  done
  if losetup "$loop" >/dev/null 2>&1; then
    echo "LFCS storage reset: failed to detach $loop" >&2
    return 1
  fi
}

detach_practice_disks() {
  local n loop seen
  for n in 1 2 3; do
    seen=' '
    while read -r loop; do
      [[ -n $loop && $seen != *" $loop "* ]] || continue
      seen+="$loop "
      swapoff_disk_tree "$loop"
      unmount_disk_tree "$loop"
    done < <(disk_candidates "$n")
  done
  remove_lab_vgs
  for n in 1 2 3; do
    seen=' '
    while read -r loop; do
      [[ -n $loop && $seen != *" $loop "* ]] || continue
      seen+="$loop "
      detach_loop "$loop"
    done < <(disk_candidates "$n")
  done
}

detach_lab_nbd() {
  # Run before lazy unmounting: the mount identifies ownership and any process
  # retaining its cwd would otherwise keep the disconnected device busy.
  /usr/local/lib/lfcs/nbd-ownership.py teardown
}

attach_blank_disk() {
  local n=$1 size=$2 file link loop
  file="$DIR/disk${n}.img"
  link="/dev/lfcs-disk${n}"
  [[ ! -e $file && ! -L $file ]] || { echo "LFCS storage: disk file still exists: $file" >&2; return 1; }
  rm -f "$link" "$file"
  truncate -s "$size" "$file"
  loop=$(losetup --find --show --partscan "$file")
  ln -s "$loop" "$link"
  blockdev --rereadpt "$loop" >/dev/null 2>&1 || true
  udevadm settle
}

validate_blank_disk() {
  local n=$1 file link loop count attached
  file="$DIR/disk${n}.img"
  link="/dev/lfcs-disk${n}"
  [[ -L $link && -b $link ]] || { echo "LFCS storage reset: $link is unavailable" >&2; return 1; }
  loop=$(readlink -f "$link")
  attached=$(losetup -j "$file" 2>/dev/null | cut -d: -f1)
  [[ $attached == "$loop" ]] || { echo "LFCS storage reset: $link has the wrong backing file" >&2; return 1; }
  count=$(lsblk -nrpo NAME "$loop" | wc -l | tr -d ' ')
  [[ $count == 1 ]] || { echo "LFCS storage reset: stale partitions remain on $link" >&2; return 1; }
  [[ -z $(wipefs -n "$loop" 2>/dev/null) ]] || { echo "LFCS storage reset: stale signatures remain on $link" >&2; return 1; }
  ! pvs "$loop" >/dev/null 2>&1 || { echo "LFCS storage reset: stale PV metadata remains on $link" >&2; return 1; }
  ! findmnt -rn -S "$loop" >/dev/null 2>&1 || { echo "LFCS storage reset: $link remains mounted" >&2; return 1; }
}

clean_lab_fstab() {
  local target_list swap_uuid disk1 disk2 disk3 tmp
  target_list=$(IFS=:; printf '%s' "${MOUNTS[*]}")
  swap_uuid=$(blkid -s UUID -o value /dev/lfcs-disk3 2>/dev/null || true)
  disk1=$(readlink -f /dev/lfcs-disk1 2>/dev/null || true)
  disk2=$(readlink -f /dev/lfcs-disk2 2>/dev/null || true)
  disk3=$(readlink -f /dev/lfcs-disk3 2>/dev/null || true)
  tmp=$(mktemp /etc/fstab.lfcs.XXXXXX)
  awk -v targets="$target_list" -v swap_uuid="$swap_uuid" \
      -v disk1="$disk1" -v disk2="$disk2" -v disk3="$disk3" '
    BEGIN {
      count = split(targets, item, ":")
      for (i = 1; i <= count; i++) owned_target[item[i]] = 1
    }
    /^[[:space:]]*#/ || NF < 2 { print; next }
    {
      source = $1
      target = $2
      gsub(/"/, "", source)
      gsub(/"/, "", target)
      sub(/\/+$/, "", target)
      if (owned_target[target]) next
      if (source == "/var/lib/lfcs-lab/exam.swap") next
      if (source == "/dev/lfcs-disk1" || source == "/dev/lfcs-disk2" || source == "/dev/lfcs-disk3") next
      if (source == disk1 || source == disk2 || source == disk3) next
      if (swap_uuid != "" && source == "UUID=" swap_uuid && $3 == "swap") next
      if ($0 ~ /#[[:space:]]*(LFCS-LAB|LFCS-EXT)[[:space:]]*$/) next
      print
    }
  ' /etc/fstab >"$tmp"
  cat "$tmp" >/etc/fstab
  rm -f "$tmp"
}

reset_all() {
  check_owned_disk_paths
  mkdir -p "$DIR" "$RUN"
  clean_lab_fstab
  # A disconnected SSHFS mount can make even stat(2)/mkdir(1) on its
  # mountpoint fail with EACCES/ENOTCONN.  Unmount every owned target before
  # attempting to create or inspect the baseline directories.
  detach_lab_nbd
  unmount_lab_paths
  mkdir -p "${MOUNTS[@]}"
  swapoff /var/lib/lfcs-lab/exam.swap >/dev/null 2>&1 || true
  detach_practice_disks
  rm -f /dev/lfcs-disk{1,2,3} "$DIR/disk1.img" "$DIR/disk2.img" "$DIR/disk3.img"
  attach_blank_disk 1 512M
  attach_blank_disk 2 384M
  attach_blank_disk 3 128M
  validate_blank_disk 1
  validate_blank_disk 2
  validate_blank_disk 3
}

case "${1:-}" in
  reset-all) reset_all ;;
  *) echo "usage: storage.sh reset-all" >&2; exit 2 ;;
esac
